"""
sql_agent.py  –  SQL generation with retry loop and session-level error memory.
Rewritten for maximum accuracy against the real-estate PostgreSQL schema.
"""

from groq import Groq
from rag import retrieve_schema
from db import run_query
import os
import re

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── Use a reliable Groq-hosted model ─────────────────────────────────────────
# Switch to a model that actually exists on Groq's API.
# Best option for SQL accuracy is llama-3.3-70b-versatile or mixtral-8x7b.
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_RETRIES = 4

# ---------------------------------------------------------------------------
# System prompt — tightly matched to the CREATE TABLE statements
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert PostgreSQL SQL generator for a real-estate portfolio database.

═══════════════════════════════════════════════════════════
RULE 0 — OUTPUT FORMAT
═══════════════════════════════════════════════════════════
Return ONLY a raw PostgreSQL SQL query.
• No markdown, no backticks, no prose, no explanation.
• Start your response with SELECT (or WITH).

═══════════════════════════════════════════════════════════
RULE 1 — EXACT TABLE & COLUMN NAMES  (case-sensitive!)
═══════════════════════════════════════════════════════════
ZoneDetails    : ZoneID, ZoneName
Regions        : RegionsId, ZoneID, RegionsName
Locations      : LocationId, ZoneID, RegionsId, LocationName
REAssets       : REAssetId, AssetName, DeveloperName, BorrowerName,
                 ZoneId, RegionsId, LocationId, Address
REUnitDetails  : REUnitDetailId, REAssetId, ProjectName, DevelopmentType,
                 ProjectType, Wing, Floor, UnitNumber, Configuration,
                 AreaConsidered, AreaConsideredMeasurement, UniqueKey
REPriceHeaders : REPriceHeaderId, REAssetID, ValueType, HeaderValue
RESales        : RESalesID, REAssetId, REUnitDetailId (varchar),
                 CustomerName, BookingDate, RegistrationDate,
                 Scheme, Financer, MISDate
REUnitSales    : REUnitSalesID, RESalesID, PriceHeader,
                 Amount (float), Demand (money), Collections (money)

═══════════════════════════════════════════════════════════
RULE 2 — ALWAYS use ILIKE for text matching
═══════════════════════════════════════════════════════════
WHERE AssetName ILIKE '%Prabadevi Address%'
NOT:  WHERE AssetName = 'Prabadevi Address'

═══════════════════════════════════════════════════════════
RULE 3 — MONEY CAST (critical — Collections & Demand are money type)
═══════════════════════════════════════════════════════════
ALWAYS cast money columns before arithmetic:
  SUM(rus.Collections::numeric)
  SUM(rus.Demand::numeric)
NEVER:  SUM(rus.Collections)   ← will silently fail

═══════════════════════════════════════════════════════════
RULE 4 — COALESCE every aggregate to avoid NULL returns
═══════════════════════════════════════════════════════════
CORRECT:  COALESCE(SUM(rus.Amount), 0)
WRONG:    SUM(rus.Amount)

═══════════════════════════════════════════════════════════
RULE 5 — CANONICAL JOIN PATTERN for sales / receivables
═══════════════════════════════════════════════════════════
This 3-table join is MANDATORY for any sales-value query:

  FROM RESales rs
  INNER JOIN REUnitSales rus ON rus.RESalesID = rs.RESalesID
  INNER JOIN REPriceHeaders rph
      ON  rph.REAssetID  = rs.REAssetId
      AND rph.HeaderValue = rus.PriceHeader
      AND rph.ValueType   = 'Sale Value'
  WHERE rs.REAssetId IN (
      SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%<name>%'
  )

⚠ If a diagnostic says 'Sale Value' is NOT present in REPriceHeaders for this
  asset, DROP the REPriceHeaders join and sum directly from REUnitSales:

  FROM RESales rs
  INNER JOIN REUnitSales rus ON rus.RESalesID = rs.RESalesID
  WHERE rs.REAssetId IN (
      SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%<name>%'
  )

═══════════════════════════════════════════════════════════
RULE 6 — AREA QUERIES
═══════════════════════════════════════════════════════════
Join REUnitDetails ↔ RESales via:
  rs.REUnitDetailId = rud.UniqueKey   (both varchar — no cast needed)

Area conversion to Sq Ft:
  COALESCE(SUM(
    CASE rud.AreaConsideredMeasurement
      WHEN 'Sq Ft'    THEN 1.0       * rud.AreaConsidered
      WHEN 'Sq mtr'   THEN 10.7639   * rud.AreaConsidered
      WHEN 'Sq yards' THEN 9.0       * rud.AreaConsidered
      ELSE rud.AreaConsidered
    END
  ), 0)

For area-sold queries, filter: rs.BookingDate IS NOT NULL
For unit-count queries, use:  COUNT(DISTINCT rs.RESalesID) and BookingDate IS NOT NULL

═══════════════════════════════════════════════════════════
RULE 7 — ZONE / REGION / LOCATION JOINS
═══════════════════════════════════════════════════════════
Zone   → REAssets.ZoneId    = ZoneDetails.ZoneID
Region → REAssets.RegionsId = Regions.RegionsId
Location → REAssets.LocationId = Locations.LocationId

═══════════════════════════════════════════════════════════
RULE 8 — DO NOT filter BookingDate IS NOT NULL for sales/receivables value queries
═══════════════════════════════════════════════════════════
Only add BookingDate IS NOT NULL for area-sold or unit-count queries.

═══════════════════════════════════════════════════════════
RULE 9 — COMPARATIVE / RANKING QUERIES
═══════════════════════════════════════════════════════════
For "which asset has least/most sales", group by asset:

  SELECT ra.AssetName,
         COALESCE(SUM(rus.Amount), 0) AS TotalSales
  FROM REAssets ra
  LEFT JOIN RESales rs ON rs.REAssetId = ra.REAssetId
  LEFT JOIN REUnitSales rus ON rus.RESalesID = rs.RESalesID
  LEFT JOIN REPriceHeaders rph
      ON  rph.REAssetID  = rs.REAssetId
      AND rph.HeaderValue = rus.PriceHeader
      AND rph.ValueType   = 'Sale Value'
  GROUP BY ra.AssetName
  ORDER BY TotalSales ASC   -- or DESC for highest
  LIMIT 5

For receivables by region:
  SELECT rg.RegionsName,
         COALESCE(SUM(rus.Amount) - SUM(rus.Collections::numeric), 0) AS Receivables
  FROM Regions rg
  JOIN REAssets ra ON ra.RegionsId = rg.RegionsId
  JOIN RESales rs ON rs.REAssetId = ra.REAssetId
  JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
  JOIN REPriceHeaders rph
      ON  rph.REAssetID  = rs.REAssetId
      AND rph.HeaderValue = rus.PriceHeader
      AND rph.ValueType   = 'Sale Value'
  GROUP BY rg.RegionsName
  ORDER BY Receivables DESC

═══════════════════════════════════════════════════════════
CANONICAL EXAMPLES — memorise these patterns exactly
═══════════════════════════════════════════════════════════

-- Q: Total sales for a named asset?
SELECT COALESCE(SUM(rus.Amount), 0) AS TotalSales
FROM RESales rs
INNER JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
INNER JOIN REPriceHeaders rph
    ON  rph.REAssetID  = rs.REAssetId
    AND rph.HeaderValue = rus.PriceHeader
    AND rph.ValueType   = 'Sale Value'
WHERE rs.REAssetId IN (
    SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%Prabadevi Address%'
);

-- Q: Balance receivables for a named asset?
SELECT COALESCE(SUM(rus.Amount) - SUM(rus.Collections::numeric), 0) AS BalanceReceivable
FROM RESales rs
INNER JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
INNER JOIN REPriceHeaders rph
    ON  rph.REAssetID  = rs.REAssetId
    AND rph.HeaderValue = rus.PriceHeader
    AND rph.ValueType   = 'Sale Value'
WHERE rs.REAssetId IN (
    SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%Prabadevi Address%'
);

-- Q: Assets in the North zone?
SELECT AssetName
FROM REAssets
WHERE ZoneId IN (
    SELECT ZoneID FROM ZoneDetails WHERE ZoneName ILIKE '%North%'
);

-- Q: Area sold in Sq Ft for a named asset?
SELECT COALESCE(SUM(
    CASE rud.AreaConsideredMeasurement
        WHEN 'Sq Ft'    THEN 1.0     * rud.AreaConsidered
        WHEN 'Sq mtr'   THEN 10.7639 * rud.AreaConsidered
        WHEN 'Sq yards' THEN 9.0     * rud.AreaConsidered
        ELSE rud.AreaConsidered
    END
), 0) AS AreaSoldSqFt
FROM REUnitDetails rud
INNER JOIN RESales rs
    ON rs.REAssetId = rud.REAssetId
   AND rs.REUnitDetailId = rud.UniqueKey
WHERE rud.REAssetId IN (
    SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%Goa Villas%'
)
AND rs.BookingDate IS NOT NULL;

-- Q: How many units sold for an asset?
SELECT COUNT(DISTINCT rs.ReSalesID) AS UnitsSold
FROM ReSales rs
WHERE rs.REAssetId IN (
    SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%Goa Villas%'
)
AND rs.BookingDate IS NOT NULL;

-- Q: Which asset has the least sales?
SELECT ra.AssetName,
       COALESCE(SUM(rus.Amount), 0) AS TotalSales
FROM REAssets ra
LEFT JOIN ReSales rs ON rs.REAssetId = ra.REAssetId
LEFT JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
LEFT JOIN REPriceHeaders rph
    ON  rph.REAssetID  = rs.REAssetId
    AND rph.HeaderValue = rus.PriceHeader
    AND rph.ValueType   = 'Sale Value'
GROUP BY ra.AssetName
ORDER BY TotalSales ASC
LIMIT 5;

-- Q: Which region has the highest receivables?
SELECT rg.RegionsName,
       COALESCE(SUM(rus.Amount) - SUM(rus.Collections::numeric), 0) AS Receivables
FROM Regions rg
JOIN REAssets ra ON ra.RegionsId = rg.RegionsId
JOIN ReSales rs ON rs.REAssetId = ra.REAssetId
JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
JOIN REPriceHeaders rph
    ON  rph.REAssetID  = rs.REAssetId
    AND rph.HeaderValue = rus.PriceHeader
    AND rph.ValueType   = 'Sale Value'
GROUP BY rg.RegionsName
ORDER BY Receivables DESC
LIMIT 1;

-- Q: Ratio of commercial to residential sales?
SELECT
    COALESCE(SUM(CASE WHEN rud.DevelopmentType ILIKE '%commercial%' THEN rus.Amount ELSE 0 END), 0)
      AS CommercialSales,
    COALESCE(SUM(CASE WHEN rud.DevelopmentType ILIKE '%residential%' THEN rus.Amount ELSE 0 END), 0)
      AS ResidentialSales
FROM REUnitDetails rud
JOIN ReSales rs
    ON rs.REAssetId = rud.REAssetId
   AND rs.REUnitDetailId = rud.UniqueKey
JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
JOIN REPriceHeaders rph
    ON  rph.REAssetID  = rs.REAssetId
    AND rph.HeaderValue = rus.PriceHeader
    AND rph.ValueType   = 'Sale Value';
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_llm(messages: list[dict]) -> str:
    """Call the LLM and return cleaned SQL text."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.0,        # deterministic — crucial for SQL accuracy
        max_tokens=1024,
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if the model wraps anyway
    raw = re.sub(r"```sql\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()

    # Drop any leading prose — keep from first SQL keyword
    match = re.search(
        r'(?im)^\s*(SELECT|WITH|INSERT|UPDATE|DELETE)',
        raw
    )
    if match:
        raw = raw[match.start():].strip()

    return raw


def _diagnose_null_result(question: str, sql: str) -> str:
    """
    When a query returns NULL / empty, run targeted diagnostics so the LLM
    can self-correct on the next attempt.
    """
    hints = []

    try:
        # ── Find ILIKE search term in generated SQL ──────────────────────────
        ilike_match = re.search(r"ILIKE\s+'%(.+?)%'", sql, re.IGNORECASE)
        if ilike_match:
            fragment = ilike_match.group(1)

            asset_rows = run_query(
                "SELECT REAssetId, AssetName FROM REAssets "
                f"WHERE AssetName ILIKE '%{fragment}%' LIMIT 5"
            )

            if not asset_rows:
                hints.append(
                    f"DIAGNOSTIC: No asset found matching '%{fragment}%'. "
                    "Spelling might be wrong."
                )
                all_assets = run_query(
                    "SELECT REAssetId, AssetName FROM REAssets ORDER BY AssetName"
                )
                if all_assets:
                    names = ", ".join(f"'{r[1]}'" for r in all_assets)
                    hints.append(f"All assets in the database: {names}")
            else:
                asset_ids = [str(r[0]) for r in asset_rows]
                id_list   = ",".join(asset_ids)
                matched   = ", ".join(f"{r[1]} (id={r[0]})" for r in asset_rows)
                hints.append(f"DIAGNOSTIC: Matched assets: {matched}")

                # Check what ValueTypes exist for those assets
                ph_rows = run_query(
                    "SELECT DISTINCT ValueType FROM REPriceHeaders "
                    f"WHERE REAssetID IN ({id_list}) ORDER BY ValueType"
                )
                vtypes = [r[0] for r in ph_rows] if ph_rows else []
                hints.append(f"DIAGNOSTIC: REPriceHeaders ValueTypes for this asset: {vtypes}")

                if "Sale Value" not in vtypes:
                    hints.append(
                        "WARNING: 'Sale Value' is NOT present in REPriceHeaders. "
                        "SOLUTION: Remove the REPriceHeaders JOIN entirely. "
                        "Sum Amount directly from REUnitSales joined to ReSales only."
                    )

                # Raw REUnitSales count
                rus_count = run_query(
                    "SELECT COUNT(*) FROM ReSales rs "
                    "JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID "
                    f"WHERE rs.REAssetId IN ({id_list})"
                )
                count = rus_count[0][0] if rus_count else 0
                hints.append(f"DIAGNOSTIC: REUnitSales rows joined to ReSales: {count}")

                if count == 0:
                    hints.append(
                        "WARNING: No REUnitSales rows at all — this asset may have no sales data."
                    )

                # Check ReSales count alone
                rs_count = run_query(
                    f"SELECT COUNT(*) FROM ReSales WHERE REAssetId IN ({id_list})"
                )
                hints.append(f"DIAGNOSTIC: ReSales rows for asset: {rs_count[0][0] if rs_count else 0}")

        else:
            # No ILIKE — could be a multi-asset / ranking query
            hints.append(
                "DIAGNOSTIC: No ILIKE pattern found in SQL. "
                "If this is a ranking/aggregate query across all assets, "
                "make sure to use LEFT JOINs so assets with no sales still appear."
            )

    except Exception as e:
        hints.append(f"DIAGNOSTIC ERROR: {e}")

    return "\n".join(hints)


def generate_sql(question: str) -> str:
    """Generate SQL from a natural-language question using RAG context."""
    schema_context = retrieve_schema(question)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Relevant schema:\n{schema_context}\n\n"
                f"Question: {question}"
            ),
        },
    ]
    sql = _call_llm(messages)
    print(f"\n[Generated SQL]\n{sql}\n")
    return sql


def execute_with_retry(question: str) -> tuple[str, list]:
    """
    Generate SQL, run it, retry with error + diagnostic feedback up to
    MAX_RETRIES times.  Returns (final_sql, rows).
    """
    schema_context = retrieve_schema(question)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Relevant schema:\n{schema_context}\n\n"
                f"Question: {question}"
            ),
        },
    ]

    sql = _call_llm(messages)
    print(f"\n[Generated SQL]\n{sql}\n")

    for attempt in range(MAX_RETRIES):
        try:
            result = run_query(sql)
            print(f"[Raw DB result]: {result}")

            # ── Detect NULL scalar ───────────────────────────────────────────
            is_null_scalar = (
                result
                and len(result) == 1
                and len(result[0]) == 1
                and result[0][0] is None
            )
            # Detect zero result that might mean a bad join (only for single-value)
            is_zero_scalar = (
                result
                and len(result) == 1
                and len(result[0]) == 1
                and result[0][0] == 0
                and attempt == 0  # only diagnose zeros on first attempt
            )

            if (is_null_scalar or is_zero_scalar) and attempt < MAX_RETRIES - 1:
                label = "NULL" if is_null_scalar else "0 (possibly a bad join)"
                print(f"[Warning] Query returned {label}. Running diagnostics…")

                diagnostic = _diagnose_null_result(question, sql)
                print(f"[Diagnostic]\n{diagnostic}\n")

                messages.append({"role": "assistant", "content": sql})
                messages.append({
                    "role": "user",
                    "content": (
                        f"The query returned {label}. Diagnostics from the live database:\n\n"
                        f"{diagnostic}\n\n"
                        "Fix the SQL based on these diagnostics.\n"
                        "• If 'Sale Value' is missing from REPriceHeaders, drop that join.\n"
                        "• If no ReSales rows exist for the asset, say so with a note query.\n"
                        "• Otherwise correct the JOIN or WHERE clause.\n"
                        "Return ONLY the corrected SQL query — no prose."
                    ),
                })
                sql = _call_llm(messages)
                print(f"[Retry {attempt + 1} SQL]\n{sql}\n")
                continue  # re-run corrected SQL

            return sql, result

        except Exception as e:
            print(f"[Attempt {attempt + 1}/{MAX_RETRIES}] SQL error: {e}")

            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(
                    f"SQL generation failed after {MAX_RETRIES} attempts.\n"
                    f"Last error: {e}\nLast SQL:\n{sql}"
                ) from e

            messages.append({"role": "assistant", "content": sql})
            messages.append({
                "role": "user",
                "content": (
                    f"That query failed with this PostgreSQL error:\n{e}\n\n"
                    "Fix the SQL — pay special attention to:\n"
                    "• money columns must be cast: ::numeric\n"
                    "• column names must match the schema exactly\n"
                    "• JOIN conditions must use the correct keys\n"
                    "Return ONLY the corrected SQL — no prose."
                ),
            })
            sql = _call_llm(messages)
            print(f"[Retry {attempt + 1}]\n{sql}\n")

    raise RuntimeError("Unexpected exit from retry loop")