"""
explorer.py  –  Dynamic table explorer API  (v2 — fixed)

Add to app.py:
    from explorer import router as explorer_router
    app.include_router(explorer_router)

Fixes vs v1:
  - money cols cast to ::numeric so Python gets Decimal, not a garbled string
  - sort_map resolves JOIN aliases (ZoneName, AssetName) to real SQL expressions
  - where_map uses fully qualified column names in WHERE clauses
  - _safe() serializer handles Decimal / date / bool / None → plain Python types
  - error detail is always a plain string (no more [object Object] in browser)
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from decimal import Decimal
import datetime, os, psycopg2

router = APIRouter(prefix="/explorer", tags=["explorer"])

# ── DB ────────────────────────────────────────────────────────────────────────

def _connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "test1"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def _safe(v):
    """Convert any psycopg2 value to a JSON-safe Python type."""
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, datetime.date):
        return str(v)
    if isinstance(v, bool):
        return str(v)
    return v


def _run(sql: str, params: list = None):
    """Run SQL, return (col_names_list, rows_list). All values safe."""
    conn = _connect()
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


# ── Table config ──────────────────────────────────────────────────────────────
#
# Keys per table:
#   select       – column names on the primary table (may include casts like "Col::numeric AS Col")
#   joins        – JOIN clause string
#   extra_select – raw SQL appended after base SELECT (for joined cols, e.g. ", ra.AssetName")
#   display_cols – final column names as returned by the query (drives UI headers + sort)
#   sort_map     – {display_col: "qualified.SQL.expr"} for ORDER BY (needed for JOIN aliases)
#   searchable   – list of qualified SQL expressions for ILIKE search
#   filterable   – {display_col: "SELECT DISTINCT …"} to populate dropdown options
#   where_map    – {display_col: "qualified.SQL.expr"} for WHERE = %s
#   date_cols    – first entry used for date-range filter
#   amount_cols  – first entry used for amount-range filter
#   sum_cols     – columns to SUM in the stats bar

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
        # Cast money cols to numeric so Python receives Decimal, not a '$' string
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


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/tables")
def list_tables():
    return {
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


@router.get("/filter-options/{table}")
def get_filter_options(table: str):
    if table not in TABLE_CONFIG:
        raise HTTPException(404, f"Table '{table}' not found")
    options = {}
    for col, sql in TABLE_CONFIG[table].get("filterable", {}).items():
        try:
            _, rows = _run(sql)
            options[col] = [str(r[0]) for r in rows if r[0] != ""]
        except Exception:
            options[col] = []
    return options


@router.get("/data/{table}")
def get_table_data(
    table:        str,
    page:         int             = Query(1, ge=1),
    page_size:    int             = Query(25, ge=1, le=200),
    sort_col:     str             = Query(""),
    sort_dir:     str             = Query("asc"),
    search:       str             = Query(""),
    date_from:    str             = Query(""),
    date_to:      str             = Query(""),
    amount_min:   Optional[str] = Query(None),
    amount_max:   Optional[str] = Query(None),
    filter_ZoneName:                  str = Query(""),
    filter_AssetName:                 str = Query(""),
    filter_Scheme:                    str = Query(""),
    filter_PriceHeader:               str = Query(""),
    filter_ValueType:                 str = Query(""),
    filter_DevelopmentType:           str = Query(""),
    filter_AreaConsideredMeasurement: str = Query(""),
):
    if table not in TABLE_CONFIG:
        raise HTTPException(404, f"Table '{table}' not found")

    cfg = TABLE_CONFIG[table]

    # Safely parse amount strings — empty string or None both become None
    def _to_float(s):
        try: return float(s) if s else None
        except (TypeError, ValueError): return None

    amt_min = _to_float(amount_min)
    amt_max = _to_float(amount_max)

    raw_filters = {
        "ZoneName":               filter_ZoneName,
        "AssetName":              filter_AssetName,
        "Scheme":                 filter_Scheme,
        "PriceHeader":            filter_PriceHeader,
        "ValueType":              filter_ValueType,
        "DevelopmentType":        filter_DevelopmentType,
        "AreaConsideredMeasurement": filter_AreaConsideredMeasurement,
    }
    active = {k: v for k, v in raw_filters.items()
              if v and k in cfg.get("filterable", {})}

    where, params = _build_where(cfg, active, search, date_from, date_to,
                                  amt_min, amt_max)

    # Build SELECT list — entries with "::" or "AS" are raw SQL, others get table prefix
    def _sel(c):
        return c if ("::" in c or " AS " in c or "." in c) else f"{table}.{c}"

    base_select = ", ".join(_sel(c) for c in cfg["select"])
    extra  = cfg.get("extra_select", "")
    joins  = cfg.get("joins", "")
    offset = (page - 1) * page_size

    # Sort — resolve alias through sort_map, then fall back to bare column name
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

        return {
            "columns":     cols,
            "rows":        rows,
            "total":       total,
            "page":        page,
            "page_size":   page_size,
            "total_pages": max(1, -(-total // page_size)),
            "stats":       stats,
            "count_label": cfg["count_label"],
        }

    except Exception as e:
        # Always return a plain string — never let psycopg2/Python objects leak to browser
        raise HTTPException(500, detail=f"{type(e).__name__}: {e}")