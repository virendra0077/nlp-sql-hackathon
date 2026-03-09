"""
app.py - FastAPI backend
Run with: uvicorn app:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time, sys, os
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sql_agent import execute_with_retry
from db import run_query
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
            "question":    request.question,
            "sql":         sql,
            "result":      [list(row) for row in result],
            "duration_ms": duration_ms,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/run-sql")
async def run_sql(request: RunSQLRequest):
    """Run a raw SQL query directly."""
    try:
        result = run_query(request.sql)
        return {
            "result": [list(row) for row in result],
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
        assets = run_query(
            f"SELECT REAssetId, AssetName FROM REAssets "
            f"WHERE AssetName ILIKE '%{asset_name}%'"
        )
        if not assets:
            return {"error": f"No asset found matching '%{asset_name}%'"}

        asset_id = assets[0][0]

        vtypes = run_query(
            f"SELECT DISTINCT ValueType FROM REPriceHeaders WHERE REAssetID = {asset_id}"
        )
        rs_count = run_query(
            f"SELECT COUNT(*) FROM ReSales WHERE REAssetId = {asset_id}"
        )
        rus_count = run_query(
            f"SELECT COUNT(*) FROM ReSales rs "
            f"JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID "
            f"WHERE rs.REAssetId = {asset_id}"
        )
        sample = run_query(
            f"SELECT COALESCE(SUM(rus.Amount),0) FROM ReSales rs "
            f"JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID "
            f"WHERE rs.REAssetId = {asset_id}"
        )

        return {
            "asset":          assets[0][1],
            "asset_id":       asset_id,
            "value_types":    [r[0] for r in vtypes],
            "resales_count":  rs_count[0][0],
            "reunit_count":   rus_count[0][0],
            "raw_sum_amount": sample[0][0] if sample else None,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/health")
def health():
    return {"status": "ok"}