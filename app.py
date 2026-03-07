"""
app.py - FastAPI backend
Run with: uvicorn app:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import time, sys, os

load_dotenv()

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sql_agent import execute_with_retry
from db import run_query

# ── Import and register the explorer router ───────────────────────────────────
from explorer_v2 import router as explorer_router

app = FastAPI(title="Real Estate SQL Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(explorer_router)


# ── Models ────────────────────────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str

class RunSQLRequest(BaseModel):
    sql: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_result(result: list) -> str:
    """
    Format query result for display.

    Crore threshold: 1 Crore = 10,000,000  (10^7)
    The original code used > 10_000_000 which is correct, but missed that
    SUM(Amount) returns values already in the base currency unit (e.g. rupees).
    We preserve that logic but also handle negative values (receivables) cleanly.
    """
    if not result:
        return "No data found."

    # ── Single scalar result ──────────────────────────────────────────────────
    if len(result) == 1 and len(result[0]) == 1:
        val = result[0][0]
        if val is None:
            return "No matching data found. Check the asset name exists in the database."
        try:
            num = float(val)
            # Anything >= 1 Lakh (100,000) display as Crore for this real-estate context
            # The data is in absolute rupee values; 1 Cr = 10^7
            abs_num = abs(num)
            sign = "-" if num < 0 else ""
            if abs_num >= 10_000_000:          # >= 1 Crore
                return f"{sign}Rs {abs_num / 10_000_000:,.2f} Cr"
            elif abs_num >= 100_000:            # >= 1 Lakh
                return f"{sign}Rs {abs_num / 100_000:,.2f} L"
            elif abs_num == int(abs_num):       # whole number (e.g. unit count, area)
                return f"{sign}{int(abs_num):,}"
            else:
                return f"{sign}{abs_num:,.2f}"
        except (TypeError, ValueError):
            return str(val)

    # ── Multi-row result ──────────────────────────────────────────────────────
    rows = []
    for row in result:
        parts = []
        for c in row:
            if c is None:
                parts.append("—")
            else:
                # Try to format numbers nicely in tables too
                try:
                    num = float(c)
                    if abs(num) >= 10_000_000:
                        parts.append(f"Rs {num / 10_000_000:,.2f} Cr")
                    elif abs(num) == int(abs(num)) and len(str(int(abs(num)))) <= 10:
                        # Likely an ID or count — don't reformat
                        parts.append(str(c))
                    else:
                        parts.append(str(c))
                except (TypeError, ValueError):
                    parts.append(str(c))
        rows.append(" | ".join(parts))
    return "\n".join(rows)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/ask")
async def ask_question(request: QuestionRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    start = time.time()
    try:
        sql, result = execute_with_retry(request.question)
        duration_ms = int((time.time() - start) * 1000)
        return {
            "question":         request.question,
            "sql":              sql,
            "result":           [list(row) for row in result],
            "formatted_result": format_result(result),
            "duration_ms":      duration_ms,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/run-sql")
async def run_sql(request: RunSQLRequest):
    """Run a reference SQL query directly (for verification page)."""
    try:
        result = run_query(request.sql)
        return {
            "result":           [list(row) for row in result],
            "formatted_result": format_result(result),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/debug/assets")
def debug_assets(search: str = ""):
    """
    Debug endpoint — shows exact AssetNames stored in the DB.
    Usage: http://localhost:8000/debug/assets?search=Goa
    """
    try:
        if search:
            rows = run_query(
                f"SELECT REAssetId, AssetName FROM REAssets "
                f"WHERE AssetName ILIKE '%{search}%' ORDER BY AssetName"
            )
        else:
            rows = run_query("SELECT REAssetId, AssetName FROM REAssets ORDER BY AssetName")
        return [{"id": r[0], "name": r[1]} for r in rows]
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/debug/price-headers")
def debug_price_headers(asset_id: int = None):
    """
    Debug endpoint — shows REPriceHeaders rows for an asset.
    Usage: http://localhost:8000/debug/price-headers?asset_id=5
    """
    try:
        if asset_id:
            rows = run_query(
                f"SELECT * FROM REPriceHeaders WHERE REAssetID = {asset_id}"
            )
        else:
            rows = run_query("SELECT * FROM REPriceHeaders LIMIT 50")
        return [
            {"id": r[0], "asset_id": r[1], "value_type": r[2], "header_value": r[3]}
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/debug/sales-check")
def debug_sales_check(asset_name: str = ""):
    """
    Debug endpoint — verifies the full sales join for a given asset name.
    Usage: http://localhost:8000/debug/sales-check?asset_name=Prabadevi
    """
    try:
        # 1. Check asset exists
        assets = run_query(
            f"SELECT REAssetId, AssetName FROM REAssets "
            f"WHERE AssetName ILIKE '%{asset_name}%'"
        )
        if not assets:
            return {"error": f"No asset found matching '%{asset_name}%'"}

        asset_id = assets[0][0]

        # 2. Check REPriceHeaders ValueTypes
        vtypes = run_query(
            f"SELECT DISTINCT ValueType FROM REPriceHeaders WHERE REAssetID = {asset_id}"
        )

        # 3. Check ReSales count
        rs_count = run_query(
            f"SELECT COUNT(*) FROM ReSales WHERE REAssetId = {asset_id}"
        )

        # 4. Check REUnitSales count via join
        rus_count = run_query(
            f"SELECT COUNT(*) FROM ReSales rs "
            f"JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID "
            f"WHERE rs.REAssetId = {asset_id}"
        )

        # 5. Sample Amount
        sample = run_query(
            f"SELECT COALESCE(SUM(rus.Amount),0) FROM ReSales rs "
            f"JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID "
            f"WHERE rs.REAssetId = {asset_id}"
        )

        return {
            "asset":         assets[0][1],
            "asset_id":      asset_id,
            "value_types":   [r[0] for r in vtypes],
            "resales_count": rs_count[0][0],
            "reunit_count":  rus_count[0][0],
            "raw_sum_amount": sample[0][0] if sample else None,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/health")
def health():
    return {"status": "ok"}