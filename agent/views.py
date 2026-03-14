"""
agent/views.py — Django views replacing the FastAPI app.py routes.
All endpoints require login except /health.
"""

import json
import os
import sys
import time

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import render

# Add project root to path so db / sql_agent / rag are importable.
# Use insert(0, ...) only once; guard against duplicates.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _get_db():
    """Lazy import of run_query to avoid circular imports at Django startup."""
    from db import run_query
    return run_query


def _get_agent():
    """Lazy import of execute_with_retry."""
    from sql_agent import execute_with_retry
    return execute_with_retry


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json_body(request) -> dict:
    """Parse JSON request body; return {} on failure."""
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}


def format_result(result: list) -> str:
    if not result:
        return "No data found."

    if len(result) == 1 and len(result[0]) == 1:
        val = result[0][0]
        if val is None:
            return "No matching data found. Check the asset name exists in the database."
        try:
            num     = float(val)
            abs_num = abs(num)
            sign    = "-" if num < 0 else ""
            if abs_num >= 10_000_000:
                return f"{sign}Rs {abs_num / 10_000_000:,.2f} Cr"
            elif abs_num >= 100_000:
                return f"{sign}Rs {abs_num / 100_000:,.2f} L"
            elif abs_num == int(abs_num):
                return f"{sign}{int(abs_num):,}"
            else:
                return f"{sign}{abs_num:,.2f}"
        except (TypeError, ValueError):
            return str(val)

    rows = []
    for row in result:
        parts = []
        for c in row:
            if c is None:
                parts.append("—")
            else:
                try:
                    num = float(c)
                    if abs(num) >= 10_000_000:
                        parts.append(f"Rs {num / 10_000_000:,.2f} Cr")
                    else:
                        parts.append(str(c))
                except (TypeError, ValueError):
                    parts.append(str(c))
        rows.append(" | ".join(parts))
    return "\n".join(rows)


# ── Views ─────────────────────────────────────────────────────────────────────

@login_required
def index(request):
    """Serve the main chat UI."""
    return render(request, "index.html", {"user": request.user})


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def ask(request):
    body     = _json_body(request)
    question = body.get("question", "").strip()
    if not question:
        return JsonResponse({"error": "Question cannot be empty."}, status=400)

    start = time.time()
    try:
        execute_with_retry = _get_agent()
        sql, result = execute_with_retry(question)
        duration_ms = int((time.time() - start) * 1000)
        return JsonResponse({
            "question":         question,
            "sql":              sql,
            "result":           [list(row) for row in result],
            "formatted_result": format_result(result),
            "duration_ms":      duration_ms,
        })
    except RuntimeError as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def run_sql(request):
    body = _json_body(request)
    sql  = body.get("sql", "").strip()
    if not sql:
        return JsonResponse({"error": "SQL cannot be empty."}, status=400)
    try:
        run_query = _get_db()
        result = run_query(sql)
        return JsonResponse({
            "result":           [list(row) for row in result],
            "formatted_result": format_result(result),
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_http_methods(["GET"])
def debug_assets(request):
    search = request.GET.get("search", "")
    run_query = _get_db()
    try:
        if search:
            rows = run_query(
                f"SELECT REAssetId, AssetName FROM REAssets "
                f"WHERE AssetName ILIKE '%{search}%' ORDER BY AssetName"
            )
        else:
            rows = run_query("SELECT REAssetId, AssetName FROM REAssets ORDER BY AssetName")
        return JsonResponse([{"id": r[0], "name": r[1]} for r in rows], safe=False)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def debug_price_headers(request):
    asset_id  = request.GET.get("asset_id")
    run_query = _get_db()
    try:
        if asset_id:
            rows = run_query(f"SELECT * FROM REPriceHeaders WHERE REAssetID = {int(asset_id)}")
        else:
            rows = run_query("SELECT * FROM REPriceHeaders LIMIT 50")
        return JsonResponse(
            [{"id": r[0], "asset_id": r[1], "value_type": r[2], "header_value": r[3]} for r in rows],
            safe=False,
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def debug_sales_check(request):
    asset_name = request.GET.get("asset_name", "")
    run_query  = _get_db()
    try:
        assets = run_query(
            f"SELECT REAssetId, AssetName FROM REAssets WHERE AssetName ILIKE '%{asset_name}%'"
        )
        if not assets:
            return JsonResponse({"error": f"No asset found matching '%{asset_name}%'"})

        asset_id  = assets[0][0]
        vtypes    = run_query(
            f"SELECT DISTINCT ValueType FROM REPriceHeaders WHERE REAssetID = {asset_id}"
        )
        rs_count  = run_query(f"SELECT COUNT(*) FROM ReSales WHERE REAssetId = {asset_id}")
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
        return JsonResponse({
            "asset":          assets[0][1],
            "asset_id":       asset_id,
            "value_types":    [r[0] for r in vtypes],
            "resales_count":  rs_count[0][0],
            "reunit_count":   rus_count[0][0],
            "raw_sum_amount": sample[0][0] if sample else None,
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["GET"])
def health(request):
    return JsonResponse({"status": "ok"})