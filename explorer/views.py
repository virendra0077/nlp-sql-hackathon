"""
explorer/views.py — Table explorer views (ported from explorer_v2.py).
All endpoints require login.
"""

import os
import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.shortcuts import render


# ── DB helpers ────────────────────────────────────────────────────────────────

def _safe(v):
    if v is None:                        return ""
    if isinstance(v, Decimal):           return float(v)
    if isinstance(v, datetime.datetime): return v.strftime("%Y-%m-%d")
    if isinstance(v, datetime.date):     return str(v)
    if isinstance(v, bool):              return str(v)
    return v


def _run(sql: str, params: list = None):
    """Open a fresh psycopg2 connection, run sql, return (cols, rows)."""
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "test1"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        port=os.getenv("DB_PORT", "5432"),
    )
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        rows = [[_safe(v) for v in row] for row in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
    return cols, rows


def _scalar(sql: str, params: list = None):
    _, rows = _run(sql, params or [])
    return rows[0][0] if rows else 0


# ── Table config (identical to explorer_v2.py) ────────────────────────────────

TABLE_CONFIG = {
    "REAssets": {
        "select":       ["REAssetId", "AssetName", "DeveloperName",
                         "BorrowerName", "ZoneId", "RegionsId", "LocationId"],
        "joins":        "LEFT JOIN ZoneDetails zd ON zd.ZoneID = REAssets.ZoneId",
        "extra_select": ", zd.ZoneName",
        "display_cols": ["REAssetId","AssetName","DeveloperName","BorrowerName",
                         "ZoneName","RegionsId","LocationId"],
        "sort_map":     {"ZoneName":"zd.ZoneName", "REAssetId":"REAssets.REAssetId",
                         "AssetName":"REAssets.AssetName"},
        "searchable":   ["REAssets.AssetName","REAssets.DeveloperName","REAssets.BorrowerName"],
        "filterable":   {
            "ZoneName": "SELECT DISTINCT ZoneName FROM ZoneDetails WHERE ZoneName IS NOT NULL ORDER BY ZoneName",
        },
        "where_map":    {"ZoneName":"zd.ZoneName"},
        "sum_cols":     [],
        "count_label":  "Assets",
    },
    "RESales": {
        "select":       ["RESalesID","REAssetId","CustomerName","BookingDate",
                         "RegistrationDate","Scheme","Financer"],
        "joins":        "LEFT JOIN REAssets ra ON ra.REAssetId = RESales.REAssetId",
        "extra_select": ", ra.AssetName",
        "display_cols": ["RESalesID","AssetName","CustomerName","BookingDate",
                         "RegistrationDate","Scheme","Financer"],
        "sort_map":     {"AssetName":"ra.AssetName","RESalesID":"RESales.RESalesID",
                         "BookingDate":"RESales.BookingDate"},
        "searchable":   ["RESales.CustomerName","ra.AssetName"],
        "filterable":   {
            "AssetName": "SELECT DISTINCT AssetName FROM REAssets WHERE AssetName IS NOT NULL ORDER BY AssetName",
            "Scheme":    "SELECT DISTINCT Scheme FROM RESales WHERE Scheme IS NOT NULL ORDER BY Scheme",
        },
        "where_map":    {"AssetName":"ra.AssetName","Scheme":"RESales.Scheme"},
        "date_cols":    ["BookingDate"],
        "sum_cols":     [],
        "count_label":  "Sales",
    },
    "REUnitSales": {
        "select":       ["REUnitSalesID", "RESalesID", "PriceHeader",
                         "Amount",
                         "Demand::numeric AS Demand",
                         "Collections::numeric AS Collections"],
        "joins":        "",
        "extra_select": "",
        "display_cols": ["REUnitSalesID","RESalesID","PriceHeader",
                         "Amount","Demand","Collections"],
        "sort_map":     {"REUnitSalesID":"REUnitSales.REUnitSalesID",
                         "Amount":"REUnitSales.Amount"},
        "searchable":   ["REUnitSales.PriceHeader"],
        "filterable":   {
            "PriceHeader": "SELECT DISTINCT PriceHeader FROM REUnitSales WHERE PriceHeader IS NOT NULL ORDER BY PriceHeader",
        },
        "where_map":    {"PriceHeader":"REUnitSales.PriceHeader"},
        "amount_cols":  ["Amount"],
        "sum_cols":     ["Amount"],
        "count_label":  "Unit Sales",
    },
    "REUnitDetails": {
        "select":       ["REUnitDetailId","REAssetId","ProjectName","DevelopmentType",
                         "ProjectType","Wing","Floor","UnitNumber","Configuration",
                         "AreaConsidered","AreaConsideredMeasurement"],
        "joins":        "LEFT JOIN REAssets ra ON ra.REAssetId = REUnitDetails.REAssetId",
        "extra_select": ", ra.AssetName",
        "display_cols": ["REUnitDetailId","AssetName","ProjectName","DevelopmentType",
                         "ProjectType","Wing","Floor","UnitNumber","Configuration",
                         "AreaConsidered","AreaConsideredMeasurement"],
        "sort_map":     {"AssetName":"ra.AssetName",
                         "REUnitDetailId":"REUnitDetails.REUnitDetailId",
                         "AreaConsidered":"REUnitDetails.AreaConsidered"},
        "searchable":   ["REUnitDetails.ProjectName","REUnitDetails.UnitNumber","ra.AssetName"],
        "filterable":   {
            "AssetName":  "SELECT DISTINCT AssetName FROM REAssets WHERE AssetName IS NOT NULL ORDER BY AssetName",
            "DevelopmentType": "SELECT DISTINCT DevelopmentType FROM REUnitDetails WHERE DevelopmentType IS NOT NULL ORDER BY DevelopmentType",
            "AreaConsideredMeasurement": "SELECT DISTINCT AreaConsideredMeasurement FROM REUnitDetails WHERE AreaConsideredMeasurement IS NOT NULL ORDER BY AreaConsideredMeasurement",
        },
        "where_map":    {
            "AssetName":"ra.AssetName",
            "DevelopmentType":"REUnitDetails.DevelopmentType",
            "AreaConsideredMeasurement":"REUnitDetails.AreaConsideredMeasurement",
        },
        "sum_cols":     [],
        "count_label":  "Units",
    },
    "REPriceHeaders": {
        "select":       ["REPriceHeaderId","REAssetID","ValueType","HeaderValue"],
        "joins":        "LEFT JOIN REAssets ra ON ra.REAssetId = REPriceHeaders.REAssetID",
        "extra_select": ", ra.AssetName",
        "display_cols": ["REPriceHeaderId","AssetName","ValueType","HeaderValue"],
        "sort_map":     {"AssetName":"ra.AssetName",
                         "REPriceHeaderId":"REPriceHeaders.REPriceHeaderId"},
        "searchable":   ["ra.AssetName","REPriceHeaders.HeaderValue"],
        "filterable":   {
            "ValueType": "SELECT DISTINCT ValueType FROM REPriceHeaders WHERE ValueType IS NOT NULL ORDER BY ValueType",
            "AssetName": "SELECT DISTINCT AssetName FROM REAssets WHERE AssetName IS NOT NULL ORDER BY AssetName",
        },
        "where_map":    {"ValueType":"REPriceHeaders.ValueType","AssetName":"ra.AssetName"},
        "sum_cols":     [],
        "count_label":  "Price Headers",
    },
    "ZoneDetails": {
        "select":       ["ZoneID","ZoneName"],
        "joins":        "",
        "extra_select": "",
        "display_cols": ["ZoneID","ZoneName"],
        "sort_map":     {"ZoneID":"ZoneDetails.ZoneID","ZoneName":"ZoneDetails.ZoneName"},
        "searchable":   ["ZoneDetails.ZoneName"],
        "filterable":   {},
        "where_map":    {},
        "sum_cols":     [],
        "count_label":  "Zones",
    },
}


# ── WHERE builder ─────────────────────────────────────────────────────────────

def _build_where(cfg, active_filters, search, date_from, date_to, amt_min, amt_max):
    clauses, params = [], []
    for col, val in active_filters.items():
        expr = cfg.get("where_map", {}).get(col, col)
        clauses.append(f"{expr} = %s")
        params.append(val)
    if search:
        parts = [f"CAST({c} AS TEXT) ILIKE %s" for c in cfg.get("searchable", [])]
        if parts:
            clauses.append("(" + " OR ".join(parts) + ")")
            params.extend([f"%{search}%"] * len(parts))
    if date_from and cfg.get("date_cols"):
        clauses.append(f"{cfg['date_cols'][0]} >= %s")
        params.append(date_from)
    if date_to and cfg.get("date_cols"):
        clauses.append(f"{cfg['date_cols'][0]} <= %s")
        params.append(date_to)
    if amt_min is not None and cfg.get("amount_cols"):
        clauses.append(f"{cfg['amount_cols'][0]} >= %s")
        params.append(amt_min)
    if amt_max is not None and cfg.get("amount_cols"):
        clauses.append(f"{cfg['amount_cols'][0]} <= %s")
        params.append(amt_max)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# ── Views ─────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def list_tables(request):
    data = {
        name: {
            "display_cols": cfg["display_cols"],
            "filterable":   list(cfg.get("filterable", {}).keys()),
            "has_date":     "date_cols" in cfg,
            "has_amount":   "amount_cols" in cfg,
            "sum_cols":     cfg.get("sum_cols", []),
            "count_label":  cfg.get("count_label", "Rows"),
        }
        for name, cfg in TABLE_CONFIG.items()
    }
    return JsonResponse(data)


@login_required
@require_http_methods(["GET"])
def filter_options(request, table: str):
    if table not in TABLE_CONFIG:
        return JsonResponse({"error": f"Table '{table}' not found"}, status=404)
    options = {}
    for col, sql in TABLE_CONFIG[table].get("filterable", {}).items():
        try:
            _, rows = _run(sql)
            options[col] = [str(r[0]) for r in rows if r[0] != ""]
        except Exception:
            options[col] = []
    return JsonResponse(options)


@login_required
@require_http_methods(["GET"])
def table_data(request, table: str):
    if table not in TABLE_CONFIG:
        return JsonResponse({"error": f"Table '{table}' not found"}, status=404)

    cfg       = TABLE_CONFIG[table]
    get       = request.GET

    page      = max(1, int(get.get("page", 1)))
    page_size = min(200, max(1, int(get.get("page_size", 25))))
    sort_col  = get.get("sort_col", "")
    sort_dir  = get.get("sort_dir", "asc")
    search    = get.get("search", "")
    date_from = get.get("date_from", "")
    date_to   = get.get("date_to", "")

    def _to_float(s):
        try: return float(s) if s else None
        except (TypeError, ValueError): return None

    amt_min = _to_float(get.get("amount_min"))
    amt_max = _to_float(get.get("amount_max"))

    raw_filters = {
        "ZoneName":                  get.get("filter_ZoneName", ""),
        "AssetName":                 get.get("filter_AssetName", ""),
        "Scheme":                    get.get("filter_Scheme", ""),
        "PriceHeader":               get.get("filter_PriceHeader", ""),
        "ValueType":                 get.get("filter_ValueType", ""),
        "DevelopmentType":           get.get("filter_DevelopmentType", ""),
        "AreaConsideredMeasurement": get.get("filter_AreaConsideredMeasurement", ""),
    }
    active = {k: v for k, v in raw_filters.items() if v and k in cfg.get("filterable", {})}

    where, params = _build_where(cfg, active, search, date_from, date_to, amt_min, amt_max)

    def _sel(c):
        return c if ("::" in c or " AS " in c or "." in c) else f"{table}.{c}"

    base_select = ", ".join(_sel(c) for c in cfg["select"])
    extra  = cfg.get("extra_select", "")
    joins  = cfg.get("joins", "")
    offset = (page - 1) * page_size

    order = ""
    if sort_col and sort_col in cfg["display_cols"]:
        sort_expr = cfg.get("sort_map", {}).get(sort_col, sort_col)
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        order = f"ORDER BY {sort_expr} {direction} NULLS LAST"

    count_sql = f"SELECT COUNT(*) FROM {table} {joins} {where}"
    data_sql  = (
        f"SELECT {base_select}{extra} "
        f"FROM {table} {joins} {where} "
        f"{order} "
        f"LIMIT {page_size} OFFSET {offset}"
    )

    try:
        total      = int(_scalar(count_sql, params))
        cols, rows = _run(data_sql, params)
        stats = {}
        for sc in cfg.get("sum_cols", []):
            try:
                val = _scalar(f"SELECT SUM({table}.{sc}) FROM {table} {joins} {where}", params)
                stats[sc] = round(float(val), 2) if val not in ("", None) else 0
            except Exception:
                stats[sc] = 0

        return JsonResponse({
            "columns":     cols,
            "rows":        rows,
            "total":       total,
            "page":        page,
            "page_size":   page_size,
            "total_pages": max(1, -(-total // page_size)),
            "stats":       stats,
            "count_label": cfg["count_label"],
        })
    except Exception as e:
        return JsonResponse({"error": f"{type(e).__name__}: {e}"}, status=500)


@login_required
@require_http_methods(["GET"])
def explorer_ui(request):
    """Serve the Data Explorer HTML page."""
    return render(request, "explorer.html", {"user": request.user})