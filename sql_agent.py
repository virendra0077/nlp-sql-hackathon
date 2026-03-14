"""
sql_agent.py — SQL generation with Groq multi-key rotation.
When one key hits its rate/daily limit, automatically rotates to the next.
Place at project root alongside manage.py.

"""

import os
import re
import time
import logging

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

from rag import retrieve_schema
from db import run_query

logger = logging.getLogger(__name__)

# ── Key pool ──────────────────────────────────────────────────────────────────

def _load_keys() -> list[str]:
    """
    Load all GROQ_API_KEY_1, GROQ_API_KEY_2, GROQ_API_KEY_3 … from env.
    Also accepts the legacy GROQ_API_KEY as a fallback.
    """
    keys = []
    # Numbered keys: GROQ_API_KEY_1, GROQ_API_KEY_2, ... up to 10
    for i in range(1, 11):
        k = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
        if k:
            keys.append(k)
    # Legacy single key
    legacy = os.getenv("GROQ_API_KEY", "").strip()
    if legacy and legacy not in keys:
        keys.append(legacy)
    if not keys:
        raise RuntimeError(
            "No Groq API keys found. Set GROQ_API_KEY_1, GROQ_API_KEY_2, "
            "GROQ_API_KEY_3 in your .env file."
        )
    return keys


GROQ_KEYS:  list[str] = _load_keys()
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_RETRIES: int = 4

# Tracks which key index is currently active (rotates on exhaustion)
_key_index: int = 0

print(f"[sql_agent] Loaded {len(GROQ_KEYS)} Groq API key(s). Model: {GROQ_MODEL}")


# ── System prompt ─────────────────────────────────────────────────────────────

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
REUnitSales    : REUnitSalesID, ReSalesID, PriceHeader,
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
NEVER:  SUM(rus.Collections)

═══════════════════════════════════════════════════════════
RULE 4 — COALESCE every aggregate to avoid NULL returns
═══════════════════════════════════════════════════════════
CORRECT:  COALESCE(SUM(rus.Amount), 0)

═══════════════════════════════════════════════════════════
RULE 5 — CANONICAL JOIN PATTERN for sales / receivables
═══════════════════════════════════════════════════════════
  FROM RESales rs
  INNER JOIN REUnitSales rus ON rus.ReSalesID = rs.RESalesID
  INNER JOIN REPriceHeaders rph
      ON  rph.REAssetID   = rs.REAssetId
      AND rph.HeaderValue = rus.PriceHeader
      AND rph.ValueType   = 'Sale Value'
  WHERE rs.REAssetId IN (
      SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%<n>%'
  )

═══════════════════════════════════════════════════════════
RULE 6 — AREA QUERIES
═══════════════════════════════════════════════════════════
Join REUnitDetails to RESales via:
  rs.REUnitDetailId = rud.UniqueKey   (both varchar)

Area conversion to Sq Ft — EXACT measurement strings from DB:
  COALESCE(SUM(
    CASE rud.AreaConsideredMeasurement
      WHEN 'Sq Ft'   THEN 1.0     * rud.AreaConsidered
      WHEN 'Sq mtr'  THEN 10.7639 * rud.AreaConsidered
      WHEN 'Sq yard' THEN 9.0     * rud.AreaConsidered
      ELSE rud.AreaConsidered
    END
  ), 0)
NOTE: value is 'Sq yard' NOT 'Sq yards'.

═══════════════════════════════════════════════════════════
RULE 7 — ZONE / REGION / LOCATION JOINS
═══════════════════════════════════════════════════════════
Zone     → REAssets.ZoneId     = ZoneDetails.ZoneID
Region   → REAssets.RegionsId  = Regions.RegionsId
Location → REAssets.LocationId = Locations.LocationId

═══════════════════════════════════════════════════════════
RULE 8 — BookingDate IS NOT NULL
═══════════════════════════════════════════════════════════
NEVER add BookingDate IS NOT NULL filter.
All ReSalesID rows are valid sold units.
Remove this filter completely from all queries.

═══════════════════════════════════════════════════════════
RULE 9 — COMPARATIVE / RANKING QUERIES
═══════════════════════════════════════════════════════════
For "which asset has least/most sales", group by asset with LEFT JOINs.

═══════════════════════════════════════════════════════════
RULE 10 — UNITS SOLD vs SALES VALUE (different queries!)
═══════════════════════════════════════════════════════════
"Units sold" = COUNT(DISTINCT rs.RESalesID) WHERE BookingDate IS NOT NULL
  — does NOT need REUnitSales or REPriceHeaders join.
"Sales value" = SUM(rus.Amount) WITH REPriceHeaders 'Sale Value' join.
Never confuse the two. "How many X sold" = unit count, not value.

═══════════════════════════════════════════════════════════
RULE 11 — MONTHLY / TIME-SERIES QUERIES
═══════════════════════════════════════════════════════════
Always use DATE_TRUNC('month', rs.BookingDate) for monthly grouping.
Always include WHERE rs.BookingDate IS NOT NULL for trend queries.
Format:
  SELECT DATE_TRUNC('month', rs.BookingDate) AS SaleMonth,
         COUNT(DISTINCT rs.RESalesID)         AS UnitsSold,
         COALESCE(SUM(rus.Amount), 0)         AS TotalSales
  FROM RESales rs ...
  GROUP BY DATE_TRUNC('month', rs.BookingDate)
  ORDER BY SaleMonth

═══════════════════════════════════════════════════════════
RULE 12 — CONFIGURATION / UNIT TYPE QUERIES
═══════════════════════════════════════════════════════════
EXACT configuration values in database:
  '1 BHK', '2 BHK', '3.5 BHK', '5 BHK', 'Office', 'Shop', 'Refuge'
FORMAT: always '<number> BHK' with a SPACE — NEVER '2BHK', 'Two Bedroom', '2-BHK'.
Use ILIKE '%2 BHK%' — the space is required.

DISTINGUISH intent:
  "how many 2BHK sold"         → COUNT(DISTINCT rs.RESalesID)  — unit count
  "how many assets have 2BHK"  → COUNT(DISTINCT ra.AssetName)  — asset count

OR CONDITIONS must always be parenthesised:
  AND (rud.Configuration ILIKE '%2 BHK%' OR rud.Configuration ILIKE '%two bedroom%')
WRONG: WHERE BookingDate IS NOT NULL AND col ILIKE '%a%' OR col ILIKE '%b%'
RIGHT: WHERE BookingDate IS NOT NULL AND (col ILIKE '%a%' OR col ILIKE '%b%')

COMMERCIAL vs RESIDENTIAL: DevelopmentType is exactly 'Residential' or 'Commercial'.

Only add an asset name filter (REAssetId IN ...) if the user EXPLICITLY mentions
an asset name. "How many 2BHK sold?" → NO asset filter (entire portfolio).

RULE 13 — ZONE / REGION / PORTFOLIO AGGREGATE QUERIES
═══════════════════════════════════════════════════════════
For zone-wide, region-wide, or full-portfolio totals,
DO NOT join REPriceHeaders at all.
Sum directly from REUnitSales.

CORRECT:
  SELECT rg.RegionsName, COALESCE(SUM(rus.Amount), 0) AS TotalSales
  FROM Regions rg
  JOIN REAssets ra ON ra.RegionsId = rg.RegionsId
  JOIN ReSales rs ON rs.REAssetId = ra.REAssetId
  JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
  GROUP BY rg.RegionsName
  ORDER BY TotalSales DESC

WRONG — never do this for zone/region queries:
  JOIN REPriceHeaders rph ON rph.ValueType = 'Sale Value' ...

RULE 14 — REPriceHeaders JOIN RESTRICTION
═══════════════════════════════════════════════════════════
Only use REPriceHeaders join when:
- User asks for a SINGLE named asset's sale value
- User explicitly says "sale value only"

Never use it for:
- Zone totals
- Region totals  
- Portfolio-wide queries
- Ranking / comparison queries across multiple assets
- Developer totals
RULE 15 — SALES VELOCITY QUERIES
═══════════════════════════════════════════════════════════
Sales velocity = units sold PER MONTH.

NEVER use EXTRACT(EPOCH ...) — gives per-second values.
NEVER use only EXTRACT(MONTH ...) — returns NULL if sales 
are within same month.

ALWAYS calculate days using this EXACT formula:
  EXTRACT(DAY FROM AGE(MAX(rs.BookingDate), MIN(rs.BookingDate)))
  + EXTRACT(MONTH FROM AGE(MAX(rs.BookingDate), MIN(rs.BookingDate))) * 30
  + EXTRACT(YEAR FROM AGE(MAX(rs.BookingDate), MIN(rs.BookingDate))) * 365

CORRECT canonical query:
SELECT 
    ra.AssetName,
    COUNT(DISTINCT rs.ReSalesID) AS TotalUnitsSold,
    ROUND(
        COUNT(DISTINCT rs.ReSalesID)::numeric /
        NULLIF(
            EXTRACT(DAY FROM AGE(MAX(rs.BookingDate), MIN(rs.BookingDate)))
            + EXTRACT(MONTH FROM AGE(MAX(rs.BookingDate), MIN(rs.BookingDate))) * 30
            + EXTRACT(YEAR FROM AGE(MAX(rs.BookingDate), MIN(rs.BookingDate))) * 365
        , 0) * 30
    , 2) AS UnitsPerMonth,
    MIN(rs.BookingDate) AS FirstSale,
    MAX(rs.BookingDate) AS LastSale
FROM REAssets ra
JOIN ReSales rs ON rs.REAssetId = ra.REAssetId
WHERE rs.BookingDate IS NOT NULL
GROUP BY ra.AssetName
HAVING COUNT(DISTINCT rs.ReSalesID) > 1
ORDER BY UnitsPerMonth DESC
LIMIT 1;

Rules:
- Always use NULLIF to avoid division by zero
- Always use HAVING COUNT > 1 to exclude single-sale projects
- Always group by ra.AssetName not rud.ProjectName
- For "slowest" change ORDER BY UnitsPerMonth ASC
- Remove LIMIT 1 for full portfolio ranking
RULE 16 — UNSOLD INVENTORY QUERIES
═══════════════════════════════════════════════════════════
CORRECT join for unsold inventory:
  LEFT JOIN ReSales rs ON rs.REUnitDetailId = rud.UniqueKey
NEVER join on both REAssetId AND UniqueKey together — 
this causes many-to-many and returns wrong counts.

Formula:
  UnsoldInventory = COUNT(rud.REUnitDetailId) - COUNT(rs.RESalesID)

RULE 17 — DATE FORMATTING
═══════════════════════════════════════════════════════════
Always format dates using TO_CHAR:
  TO_CHAR(DATE_TRUNC('month', rs.BookingDate), 'YYYY-MM') AS SaleMonth
Never return raw timestamp with timezone for display.
"""


# ── SQL cleaner ───────────────────────────────────────────────────────────────

def _clean_sql(raw: str) -> str:
    """Strip markdown fences, chain-of-thought tags, extract the SQL."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"```sql\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```\s*", "", raw).strip()
    match = re.search(r'(?im)^\s*(SELECT|WITH|INSERT|UPDATE|DELETE)', raw)
    if match:
        raw = raw[match.start():].strip()
    return raw


# ── Key rotation helpers ──────────────────────────────────────────────────────

def _is_quota_error(e: Exception) -> bool:
    """Return True if the exception is a rate-limit / quota exhaustion."""
    err = str(e).lower()
    return any(x in err for x in [
        "rate_limit_exceeded", "rate limit", "429",
        "quota", "too many requests", "tokens per",
        "requests per", "exceeded",
    ])


def _rotate_key() -> bool:
    """
    Advance _key_index to the next available key.
    Returns True if a new key is available, False if all keys exhausted.
    """
    global _key_index
    next_index = _key_index + 1
    if next_index >= len(GROQ_KEYS):
        return False    # all keys exhausted
    _key_index = next_index
    masked = GROQ_KEYS[_key_index][:8] + "…"
    print(f"[sql_agent] Rotated to Groq key #{_key_index + 1} ({masked})")
    logger.warning("[sql_agent] Groq quota hit — rotated to key #%d", _key_index + 1)
    return True


def _current_client() -> Groq:
    return Groq(api_key=GROQ_KEYS[_key_index])


# ── LLM caller with key rotation ─────────────────────────────────────────────

def _call_llm(messages: list[dict]) -> str:
    """
    Call Groq. On rate-limit / quota error, rotate to the next key and retry.
    Tries every available key before raising.
    """
    keys_tried = 0
    while keys_tried <= len(GROQ_KEYS):
        try:
            client   = _current_client()
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.0,
                max_tokens=1024,
            )
            return _clean_sql(response.choices[0].message.content)

        except Exception as e:
            if _is_quota_error(e):
                keys_tried += 1
                rotated = _rotate_key()
                if rotated:
                    continue        # try next key immediately
                # All keys exhausted — check for retry hint and wait
                wait_match = re.search(
                    r"(?:retry after|please try again in|retry in)\s*(\d+(?:\.\d+)?)\s*s",
                    str(e), re.IGNORECASE,
                )
                if wait_match:
                    wait = min(float(wait_match.group(1)) + 1, 65)
                    print(f"[sql_agent] All keys exhausted. Waiting {wait:.0f}s then retrying key #1…")
                    time.sleep(wait)
                    _key_index = 0  # reset to first key after waiting
                    keys_tried  = 0
                    continue
                raise RuntimeError(
                    f"All {len(GROQ_KEYS)} Groq API keys are exhausted. "
                    "Add more keys or wait for quota reset."
                ) from e
            raise   # non-quota errors bubble up

    raise RuntimeError("Unexpected exit from key rotation loop")


# ── Diagnostics ───────────────────────────────────────────────────────────────

def _diagnose_null_result(question: str, sql: str) -> str:
    hints = []

    if "COUNT" in sql.upper() and "REUnitSales" in sql:
        hints.append(
            "DIAGNOSTIC: Unit-count queries should NOT join REUnitSales. "
            "Use COUNT(DISTINCT rs.RESalesID) FROM ReSales directly."
        )

    if "Configuration" in sql and "UniqueKey" not in sql:
        hints.append(
            "DIAGNOSTIC: Configuration queries must join REUnitDetails via "
            "rud.UniqueKey = rs.REUnitDetailId — this join is missing."
        )

    try:
        ilike_match = re.search(r"ILIKE\s+'%(.+?)%'", sql, re.IGNORECASE)
        if ilike_match:
            fragment   = ilike_match.group(1)
            asset_rows = run_query(
                f"SELECT REAssetId, AssetName FROM REAssets "
                f"WHERE AssetName ILIKE '%{fragment}%' LIMIT 5"
            )
            if not asset_rows:
                hints.append(f"DIAGNOSTIC: No asset found matching '%{fragment}%'.")
                all_assets = run_query(
                    "SELECT REAssetId, AssetName FROM REAssets ORDER BY AssetName"
                )
                if all_assets:
                    names = ", ".join(f"'{r[1]}'" for r in all_assets)
                    hints.append(f"All assets in DB: {names}")
            else:
                asset_ids = [str(r[0]) for r in asset_rows]
                id_list   = ",".join(asset_ids)
                matched   = ", ".join(f"{r[1]} (id={r[0]})" for r in asset_rows)
                hints.append(f"DIAGNOSTIC: Matched assets: {matched}")

                ph_rows = run_query(
                    f"SELECT DISTINCT ValueType FROM REPriceHeaders "
                    f"WHERE REAssetID IN ({id_list}) ORDER BY ValueType"
                )
                vtypes = [r[0] for r in ph_rows] if ph_rows else []
                hints.append(f"DIAGNOSTIC: REPriceHeaders ValueTypes available: {vtypes}")

                if "Sale Value" not in vtypes:
                    hints.append(
                        "WARNING: 'Sale Value' NOT present for this asset. "
                        "SOLUTION: Remove REPriceHeaders JOIN, sum directly from REUnitSales."
                    )

                rus_count = run_query(
                    "SELECT COUNT(*) FROM ReSales rs "
                    "JOIN REUnitSales rus ON rus.ReSalesID = rs.RESalesID "
                    f"WHERE rs.REAssetId IN ({id_list})"
                )
                count = rus_count[0][0] if rus_count else 0
                hints.append(f"DIAGNOSTIC: REUnitSales rows joined to ReSales: {count}")
        else:
            hints.append(
                "DIAGNOSTIC: No ILIKE asset filter found. "
                "Use LEFT JOINs for portfolio-wide ranking queries."
            )
    except Exception as e:
        hints.append(f"DIAGNOSTIC ERROR: {e}")

    return "\n".join(hints)


# ── Main entry point ──────────────────────────────────────────────────────────

def execute_with_retry(question: str) -> tuple[str, list]:
    schema_context = retrieve_schema(question)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"Relevant schema:\n{schema_context}\n\nQuestion: {question}"},
    ]
    sql = _call_llm(messages)

    for attempt in range(MAX_RETRIES):
        try:
            result = run_query(sql)

            is_null_scalar = (
                result
                and len(result) == 1
                and len(result[0]) == 1
                and result[0][0] is None
            )
            is_zero_scalar = (
                result
                and len(result) == 1
                and len(result[0]) == 1
                and result[0][0] == 0
                and attempt == 0
            )

            if (is_null_scalar or is_zero_scalar) and attempt < MAX_RETRIES - 1:
                label      = "NULL" if is_null_scalar else "0 (possibly a bad join)"
                diagnostic = _diagnose_null_result(question, sql)
                messages.append({"role": "assistant", "content": sql})
                messages.append({
                    "role": "user",
                    "content": (
                        f"The query returned {label}.\n\nDiagnostics:\n{diagnostic}\n\n"
                        "Fix the SQL based on the diagnostics above. "
                        "Return ONLY the corrected SQL — no prose, no markdown."
                    ),
                })
                sql = _call_llm(messages)
                continue

            return sql, result

        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(
                    f"SQL generation failed after {MAX_RETRIES} attempts.\n"
                    f"Last error: {e}\nLast SQL:\n{sql}"
                ) from e

            messages.append({"role": "assistant", "content": sql})
            messages.append({
                "role": "user",
                "content": (
                    f"That query failed with this error:\n{e}\n\n"
                    "Fix the SQL. Return ONLY the corrected SQL — no prose, no markdown."
                ),
            })
            sql = _call_llm(messages)

    raise RuntimeError("Unexpected exit from retry loop")