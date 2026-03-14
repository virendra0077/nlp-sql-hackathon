"""
sql_agent.py — SQL generation with retry loop.
Place at project root alongside manage.py.
"""

import os
import re

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

from rag import retrieve_schema
from db import run_query

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL       = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_RETRIES = 4

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
NEVER:  SUM(rus.Collections)

═══════════════════════════════════════════════════════════
RULE 4 — COALESCE every aggregate to avoid NULL returns
═══════════════════════════════════════════════════════════
CORRECT:  COALESCE(SUM(rus.Amount), 0)

═══════════════════════════════════════════════════════════
RULE 5 — CANONICAL JOIN PATTERN for sales / receivables
═══════════════════════════════════════════════════════════
  FROM RESales rs
  INNER JOIN REUnitSales rus ON rus.RESalesID = rs.RESalesID
  INNER JOIN REPriceHeaders rph
      ON  rph.REAssetID  = rs.REAssetId
      AND rph.HeaderValue = rus.PriceHeader
      AND rph.ValueType   = 'Sale Value'
  WHERE rs.REAssetId IN (
      SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%<name>%'
  )

═══════════════════════════════════════════════════════════
RULE 6 — AREA QUERIES
═══════════════════════════════════════════════════════════
Join REUnitDetails ↔ ReSales via:
  rs.REUnitDetailId = rud.UniqueKey   (both varchar)

Area conversion to Sq Ft:
  COALESCE(SUM(
    CASE rud.AreaConsideredMeasurement
      WHEN 'Sq Ft'    THEN 1.0       * rud.AreaConsidered
      WHEN 'Sq mtr'   THEN 10.7639   * rud.AreaConsidered
      WHEN 'Sq yards' THEN 9.0       * rud.AreaConsidered
      ELSE rud.AreaConsidered
    END
  ), 0)

═══════════════════════════════════════════════════════════
RULE 7 — ZONE / REGION / LOCATION JOINS
═══════════════════════════════════════════════════════════
Zone   → REAssets.ZoneId    = ZoneDetails.ZoneID
Region → REAssets.RegionsId = Regions.RegionsId
Location → REAssets.LocationId = Locations.LocationId

═══════════════════════════════════════════════════════════
RULE 8 — BookingDate IS NOT NULL only for area/unit-count queries
═══════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════
RULE 9 — COMPARATIVE / RANKING QUERIES
═══════════════════════════════════════════════════════════
For "which asset has least/most sales", group by asset with LEFT JOINs.
"""


def _call_llm(messages: list[dict]) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.0,
        max_tokens=1024,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```sql\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()
    match = re.search(r'(?im)^\s*(SELECT|WITH|INSERT|UPDATE|DELETE)', raw)
    if match:
        raw = raw[match.start():].strip()
    return raw


def _diagnose_null_result(question: str, sql: str) -> str:
    hints = []
    try:
        ilike_match = re.search(r"ILIKE\s+'%(.+?)%'", sql, re.IGNORECASE)
        if ilike_match:
            fragment = ilike_match.group(1)
            asset_rows = run_query(
                f"SELECT REAssetId, AssetName FROM REAssets "
                f"WHERE AssetName ILIKE '%{fragment}%' LIMIT 5"
            )
            if not asset_rows:
                hints.append(f"DIAGNOSTIC: No asset found matching '%{fragment}%'.")
                all_assets = run_query("SELECT REAssetId, AssetName FROM REAssets ORDER BY AssetName")
                if all_assets:
                    names = ", ".join(f"'{r[1]}'" for r in all_assets)
                    hints.append(f"All assets: {names}")
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
                hints.append(f"DIAGNOSTIC: REPriceHeaders ValueTypes: {vtypes}")
                if "Sale Value" not in vtypes:
                    hints.append(
                        "WARNING: 'Sale Value' NOT present. "
                        "SOLUTION: Remove REPriceHeaders JOIN, sum directly from REUnitSales."
                    )
                rus_count = run_query(
                    "SELECT COUNT(*) FROM ReSales rs "
                    "JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID "
                    f"WHERE rs.REAssetId IN ({id_list})"
                )
                count = rus_count[0][0] if rus_count else 0
                hints.append(f"DIAGNOSTIC: REUnitSales rows joined to ReSales: {count}")
        else:
            hints.append("DIAGNOSTIC: No ILIKE pattern. Use LEFT JOINs for ranking queries.")
    except Exception as e:
        hints.append(f"DIAGNOSTIC ERROR: {e}")
    return "\n".join(hints)


def execute_with_retry(question: str) -> tuple[str, list]:
    schema_context = retrieve_schema(question)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Relevant schema:\n{schema_context}\n\nQuestion: {question}"},
    ]
    sql = _call_llm(messages)

    for attempt in range(MAX_RETRIES):
        try:
            result = run_query(sql)
            is_null_scalar = (
                result and len(result) == 1 and len(result[0]) == 1 and result[0][0] is None
            )
            is_zero_scalar = (
                result and len(result) == 1 and len(result[0]) == 1
                and result[0][0] == 0 and attempt == 0
            )
            if (is_null_scalar or is_zero_scalar) and attempt < MAX_RETRIES - 1:
                label      = "NULL" if is_null_scalar else "0 (possibly a bad join)"
                diagnostic = _diagnose_null_result(question, sql)
                messages.append({"role": "assistant", "content": sql})
                messages.append({
                    "role": "user",
                    "content": (
                        f"The query returned {label}. Diagnostics:\n\n{diagnostic}\n\n"
                        "Fix the SQL. Return ONLY the corrected SQL query — no prose."
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
                    f"That query failed:\n{e}\n\n"
                    "Fix the SQL. Return ONLY the corrected SQL — no prose."
                ),
            })
            sql = _call_llm(messages)
    raise RuntimeError("Unexpected exit from retry loop")