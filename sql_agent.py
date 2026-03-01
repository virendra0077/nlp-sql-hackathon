"""
sql_agent.py - SQL generation with retry loop and session-level error memory.
"""

from groq import Groq
from rag import retrieve_schema
from db import run_query
import os

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MODEL = "openai/gpt-oss-120b"
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Shared system prompt — sent once per API call to keep the model aligned
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert PostgreSQL SQL generator for a real-estate database.

STRICT RULES:
1. Return ONLY a valid PostgreSQL SQL query. No explanations. No markdown.
2. Never use double quotes around table or column names.
3. Use LIKE (not ILIKE) for asset name matching: AssetName LIKE '%Name%'

4. CRITICAL JOIN PATTERN for sales/receivables — always use this exact structure:
     FROM RESales rs
     INNER JOIN REUnitSales rus ON rs.RESalesId = rus.RESalesID
     INNER JOIN REPriceHeaders rph
         ON rph.REAssetID = rs.REAssetId
        AND rph.HeaderValue = rus.PriceHeader
        AND rph.ValueType = 'Sale Value'
   REPriceHeaders must join to RESales (via REAssetID), NOT directly to REAssets.
   Joining REPriceHeaders directly to REAssets inflates row counts and gives wrong totals.

5. Filter by asset name using a subquery — do NOT join REAssets into the main query:
   WHERE rs.REAssetId IN (SELECT REAssetId FROM REAssets WHERE AssetName LIKE '%Name%')

6. Do NOT add WHERE BookingDate IS NOT NULL for sales or receivables queries.
   Only use BookingDate IS NOT NULL for area-sold queries.

7. CRITICAL TYPE RULE: REUnitSales.Amount is FLOAT. REUnitSales.Collections is MONEY.
   PostgreSQL cannot mix float and money in arithmetic. Always cast money to numeric:
     CORRECT:   SUM(rus.Amount) - SUM(rus.Collections::numeric)
     WRONG:     SUM(rus.Amount) - SUM(rus.Collections)
     WRONG:     SUM(rus.Amount)::money

8. Balance Receivable = SUM(rus.Amount) - SUM(rus.Collections::numeric)
9. Total Sales       = SUM(rus.Amount)
10. Area in Sq Ft    = SUM(CASE AreaConsideredMeasurement
        WHEN 'Sq Ft'    THEN 1       * AreaConsidered
        WHEN 'Sq mtr'   THEN 10.7639 * AreaConsidered
        WHEN 'Sq yards' THEN 9       * AreaConsidered END)
11. Zone queries: REAssets.ZoneId = ZoneDetails.ZoneID
12. Use only columns that exist in the provided schema.

CANONICAL EXAMPLES:

Q: Total sales for an asset?
SELECT SUM(rus.Amount)
FROM RESales rs
INNER JOIN REUnitSales rus ON rs.RESalesId = rus.RESalesID
INNER JOIN REPriceHeaders rph ON rph.REAssetID = rs.REAssetId
    AND rph.HeaderValue = rus.PriceHeader AND rph.ValueType = 'Sale Value'
WHERE rs.REAssetId IN (SELECT REAssetId FROM REAssets WHERE AssetName LIKE '%AssetName%');

Q: Balance receivables for an asset?
SELECT SUM(rus.Amount) - SUM(rus.Collections::numeric)
FROM RESales rs
INNER JOIN REUnitSales rus ON rs.RESalesId = rus.RESalesID
INNER JOIN REPriceHeaders rph ON rph.REAssetID = rs.REAssetId
    AND rph.HeaderValue = rus.PriceHeader AND rph.ValueType = 'Sale Value'
WHERE rs.REAssetId IN (SELECT REAssetId FROM REAssets WHERE AssetName LIKE '%AssetName%');

Q: Which assets are in the North zone?
SELECT AssetName FROM REAssets
WHERE ZoneId IN (SELECT ZoneID FROM ZoneDetails WHERE ZoneName = 'North');

Q: Area sold in Sq Ft for an asset?
SELECT SUM(CASE rud.AreaConsideredMeasurement
    WHEN 'Sq Ft'    THEN 1       * rud.AreaConsidered
    WHEN 'Sq mtr'   THEN 10.7639 * rud.AreaConsidered
    WHEN 'Sq yards' THEN 9       * rud.AreaConsidered END)
FROM REUnitDetails rud
INNER JOIN RESales rs ON rs.REAssetId = rud.REAssetId AND rs.REUnitDetailId = rud.UniqueKey
WHERE rud.REAssetId IN (SELECT REAssetId FROM REAssets WHERE AssetName LIKE '%AssetName%')
  AND rs.BookingDate IS NOT NULL;"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_llm(messages: list[dict]) -> str:
    """Call the LLM and return cleaned SQL text."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
    )
    raw = response.choices[0].message.content
    return raw.replace("```sql", "").replace("```", "").strip()


def generate_sql(question: str) -> str:
    """Generate SQL from a natural-language question using RAG context."""
    schema_context = retrieve_schema(question)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Schema:\n{schema_context}\n\n"
                f"Question:\n{question}"
            ),
        },
    ]

    sql = _call_llm(messages)
    print(f"\n[Generated SQL]\n{sql}\n")
    return sql


def execute_with_retry(question: str) -> tuple[str, list]:
    """
    Generate SQL, run it, and retry with error feedback up to MAX_RETRIES times.
    Returns (final_sql, rows).
    """
    schema_context = retrieve_schema(question)

    # Build a conversation so the model sees its own errors and fixes them
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Schema:\n{schema_context}\n\n"
                f"Question:\n{question}"
            ),
        },
    ]

    sql = _call_llm(messages)
    print(f"\n[Generated SQL]\n{sql}\n")

    for attempt in range(MAX_RETRIES):
        try:
            result = run_query(sql)
            return sql, result

        except Exception as e:
            print(f"[Attempt {attempt + 1}/{MAX_RETRIES}] SQL error: {e}")

            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(
                    f"SQL generation failed after {MAX_RETRIES} attempts.\n"
                    f"Last error: {e}\nLast SQL:\n{sql}"
                ) from e

            # Feed the error back into the conversation so the model can self-correct
            messages.append({"role": "assistant", "content": sql})
            messages.append({
                "role": "user",
                "content": (
                    f"That query failed with this PostgreSQL error:\n{e}\n\n"
                    "Fix the SQL. Return ONLY the corrected SQL query."
                ),
            })

            sql = _call_llm(messages)
            print(f"[Retry {attempt + 1}]\n{sql}\n")

    # Should never reach here
    raise RuntimeError("Unexpected exit from retry loop")

