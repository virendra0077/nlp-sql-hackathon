"""
rag.py — Schema retrieval via FAISS vector search.
Place at project root alongside manage.py.
"""

import os
import numpy as np

_TOP_K       = 12
_MODEL_NAME  = "all-MiniLM-L6-v2"
_SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "schema.txt")

_model     = None
_index     = None
_documents: list[str] = []

_HARDCODED_CHUNKS = [
    """Table: ZoneDetails — stores geographic zones (North, East, West, South).
Columns: ZoneID (PK int), ZoneName (varchar).
Use for: "which zone is X in?", "assets in North", "zone performance".
JOIN:    REAssets.ZoneId = ZoneDetails.ZoneID""",

    """Table: Regions — sub-divisions within zones.
Columns: RegionsId (PK int), ZoneID (FK), RegionsName (varchar).
Use for: "which region has the highest receivables?", "region-wise sales".
JOIN:    REAssets.RegionsId = Regions.RegionsId""",

    """Table: Locations — further subdivision within regions.
Columns: LocationId (PK int), ZoneID, RegionsId, LocationName (varchar).
Use for: "assets in a specific location".
JOIN:    REAssets.LocationId = Locations.LocationId""",

    """Table: REAssets — master table of real estate assets / projects.
Columns: REAssetId (PK int), AssetName (varchar), DeveloperName, BorrowerName,
         ZoneId (FK→ZoneDetails.ZoneID), RegionsId (FK→Regions.RegionsId),
         LocationId (FK→Locations.LocationId), Address.
Use for: "find asset by name", "assets in a zone/region", "developer info".
Text matching: always use ILIKE '%name%' — never exact match.""",

    """Table: REUnitDetails — individual units / apartments within an asset.
Columns: REUnitDetailId (PK int), REAssetId (FK), ProjectName, DevelopmentType
         (e.g. 'Residential', 'Commercial'), ProjectType, Wing, Floor,
         UnitNumber, Configuration (e.g. '2BHK'), AreaConsidered (float),
         AreaConsideredMeasurement ('Sq Ft'|'Sq mtr'|'Sq yards'), UniqueKey (varchar).
Use for: "area sold", "unit configuration", "commercial vs residential ratio".
JOIN to ReSales: rs.REUnitDetailId = rud.UniqueKey  (BOTH are varchar)
Area to Sq Ft:
  CASE rud.AreaConsideredMeasurement
    WHEN 'Sq Ft'    THEN 1.0       * rud.AreaConsidered
    WHEN 'Sq mtr'   THEN 10.7639   * rud.AreaConsidered
    WHEN 'Sq yards' THEN 9.0       * rud.AreaConsidered
  END""",

    """Table: REPriceHeaders — maps price-header labels to ValueTypes per asset.
Columns: REPriceHeaderId (PK int), REAssetID (FK→REAssets.REAssetId),
         ValueType (varchar, e.g. 'Sale Value'), HeaderValue (varchar).
Use for: connecting REUnitSales.PriceHeader to a ValueType.
Critical JOIN (for sales value queries):
  REPriceHeaders rph
    ON rph.REAssetID   = rs.REAssetId
   AND rph.HeaderValue = rus.PriceHeader
   AND rph.ValueType   = 'Sale Value'
WARNING: some assets may NOT have a 'Sale Value' row — if diagnostics show
this, DROP the REPriceHeaders join and sum directly from REUnitSales.""",

    """Table: ReSales — one row per sale transaction.
Columns: ReSalesID (PK int), REAssetId (FK), REUnitDetailId (varchar FK→UniqueKey),
         CustomerName, BookingDate (date), RegistrationDate (date),
         Scheme (varchar), Financer (varchar), MISDate (date).
Use for: "how many units sold", "booking date filter", "customer info".
Unit count: COUNT(DISTINCT rs.ReSalesID) WHERE BookingDate IS NOT NULL
Do NOT filter BookingDate IS NOT NULL for sales-value or receivables queries.""",

    """Table: REUnitSales — financial breakdown of each sale.
Columns: REUnitSalesID (PK int), ReSalesID (FK→ReSales.ReSalesID),
         PriceHeader (varchar), Amount (float), Demand (money), Collections (money).
Use for: "total sales value", "balance receivable", "collections".
CRITICAL TYPE RULES:
  Amount      is FLOAT   → SUM(rus.Amount) works directly
  Collections is MONEY   → MUST cast: SUM(rus.Collections::numeric)
  Demand      is MONEY   → MUST cast: SUM(rus.Demand::numeric)
Formulas:
  Total Sales        = COALESCE(SUM(rus.Amount), 0)
  Balance Receivable = COALESCE(SUM(rus.Amount) - SUM(rus.Collections::numeric), 0)""",

    """Canonical SQL for total sales of a named asset:
SELECT COALESCE(SUM(rus.Amount), 0) AS TotalSales
FROM ReSales rs
INNER JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
INNER JOIN REPriceHeaders rph
    ON rph.REAssetID = rs.REAssetId
   AND rph.HeaderValue = rus.PriceHeader
   AND rph.ValueType = 'Sale Value'
WHERE rs.REAssetId IN (
    SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%AssetName%'
);""",

    """Canonical SQL for balance receivables of a named asset:
SELECT COALESCE(SUM(rus.Amount) - SUM(rus.Collections::numeric), 0) AS BalanceReceivable
FROM ReSales rs
INNER JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
INNER JOIN REPriceHeaders rph
    ON rph.REAssetID = rs.REAssetId
   AND rph.HeaderValue = rus.PriceHeader
   AND rph.ValueType = 'Sale Value'
WHERE rs.REAssetId IN (
    SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%AssetName%'
);""",

    """Canonical SQL for area sold in Sq Ft for a named asset:
SELECT COALESCE(SUM(
    CASE rud.AreaConsideredMeasurement
        WHEN 'Sq Ft'    THEN 1.0       * rud.AreaConsidered
        WHEN 'Sq mtr'   THEN 10.7639   * rud.AreaConsidered
        WHEN 'Sq yards' THEN 9.0       * rud.AreaConsidered
        ELSE rud.AreaConsidered
    END
), 0) AS AreaSoldSqFt
FROM REUnitDetails rud
INNER JOIN ReSales rs
    ON rs.REAssetId = rud.REAssetId
   AND rs.REUnitDetailId = rud.UniqueKey
WHERE rud.REAssetId IN (
    SELECT REAssetId FROM REAssets WHERE AssetName ILIKE '%AssetName%'
)
AND rs.BookingDate IS NOT NULL;""",

"""Canonical SQL for ranking assets by sales (least/most):
SELECT ra.AssetName,
       COALESCE(SUM(rus.Amount), 0) AS TotalSales
FROM REAssets ra
LEFT JOIN ReSales rs ON rs.REAssetId = ra.REAssetId
LEFT JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
GROUP BY ra.AssetName
ORDER BY TotalSales ASC
LIMIT 5;

Canonical SQL for region with highest receivables:
SELECT rg.RegionsName,
       COALESCE(SUM(rus.Amount) - SUM(rus.Collections::numeric), 0) AS Receivables
FROM Regions rg
JOIN REAssets ra ON ra.RegionsId = rg.RegionsId
JOIN ReSales rs ON rs.REAssetId = ra.REAssetId
JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
GROUP BY rg.RegionsName
ORDER BY Receivables DESC
LIMIT 1;
NOTE: No REPriceHeaders join for any ranking/zone/region query.""",

"""Canonical SQL for region with highest sales or receivables:
SELECT rg.RegionsName,
       COALESCE(SUM(rus.Amount), 0) AS TotalSales,
       COALESCE(SUM(rus.Amount) - SUM(rus.Collections::numeric), 0) AS Receivables
FROM Regions rg
JOIN REAssets ra ON ra.RegionsId = rg.RegionsId
JOIN ReSales rs ON rs.REAssetId = ra.REAssetId
JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
GROUP BY rg.RegionsName
ORDER BY TotalSales DESC
LIMIT 1;
NOTE: Never join REPriceHeaders for region/zone aggregate queries.""",
"""Canonical SQL for average unit price per configuration:
SELECT rud.Configuration,
       COALESCE(AVG(rus.Amount), 0) AS AvgUnitPrice,
       COUNT(DISTINCT rs.RESalesID) AS UnitsSold
FROM RESales rs
INNER JOIN REUnitSales rus ON rus.ReSalesID = rs.RESalesID
INNER JOIN REPriceHeaders rph
    ON rph.REAssetID  = rs.REAssetId
   AND rph.HeaderValue = rus.PriceHeader
   AND rph.ValueType   = 'Sale Value'
INNER JOIN REUnitDetails rud
    ON rud.REAssetId  = rs.REAssetId
   AND rud.UniqueKey  = rs.REUnitDetailId
GROUP BY rud.Configuration
ORDER BY AvgUnitPrice DESC;""",

"""Canonical SQL for developer with highest total sales:
SELECT ra.DeveloperName,
       COALESCE(SUM(rus.Amount), 0) AS TotalSales
FROM REAssets ra
LEFT JOIN RESales rs ON rs.REAssetId = ra.REAssetId
LEFT JOIN REUnitSales rus ON rus.ReSalesID = rs.RESalesID
LEFT JOIN REPriceHeaders rph
    ON rph.REAssetID   = rs.REAssetId
   AND rph.HeaderValue = rus.PriceHeader
   AND rph.ValueType   = 'Sale Value'
GROUP BY ra.DeveloperName
ORDER BY TotalSales DESC
LIMIT 5;""",

"""Canonical SQL for monthly sales trend:
SELECT DATE_TRUNC('month', rs.BookingDate) AS SaleMonth,
       COUNT(DISTINCT rs.RESalesID)         AS UnitsSold,
       COALESCE(SUM(rus.Amount), 0)         AS TotalSales
FROM RESales rs
INNER JOIN REUnitSales rus ON rus.ReSalesID = rs.RESalesID
INNER JOIN REPriceHeaders rph
    ON rph.REAssetID   = rs.REAssetId
   AND rph.HeaderValue = rus.PriceHeader
   AND rph.ValueType   = 'Sale Value'
WHERE rs.BookingDate IS NOT NULL
GROUP BY DATE_TRUNC('month', rs.BookingDate)
ORDER BY SaleMonth;""",

"""Canonical SQL for asset with maximum units sold:
SELECT ra.AssetName,
       COUNT(DISTINCT rs.RESalesID) AS UnitsSold
FROM REAssets ra
LEFT JOIN ReSales rs ON rs.REAssetId = ra.REAssetId
GROUP BY ra.AssetName
ORDER BY UnitsSold DESC
LIMIT 1;
NOTE: Never filter BookingDate IS NOT NULL for unit count queries.""",

"""Canonical SQL for revenue per region within each zone:
SELECT zd.ZoneName,
       rg.RegionsName,
       COALESCE(SUM(rus.Amount), 0) AS TotalRevenue
FROM ZoneDetails zd
JOIN Regions rg      ON rg.ZoneID     = zd.ZoneID
JOIN REAssets ra     ON ra.RegionsId  = rg.RegionsId
JOIN ReSales rs      ON rs.REAssetId  = ra.REAssetId
JOIN REUnitSales rus ON rus.ReSalesID = rs.RESalesID
JOIN REPriceHeaders rph
    ON rph.REAssetID   = rs.REAssetId
   AND rph.HeaderValue = rus.PriceHeader
   AND rph.ValueType   = 'Sale Value'
GROUP BY zd.ZoneName, rg.RegionsName
ORDER BY zd.ZoneName, TotalRevenue DESC;""",

"""Canonical SQL for count of units sold by configuration (e.g. 2BHK):
SELECT rud.Configuration,
       COUNT(DISTINCT rs.RESalesID) AS UnitsSold
FROM RESales rs
INNER JOIN REUnitDetails rud
    ON rud.REAssetId = rs.REAssetId
   AND rud.UniqueKey = rs.REUnitDetailId
WHERE rs.BookingDate IS NOT NULL
GROUP BY rud.Configuration
ORDER BY UnitsSold DESC;

-- For a specific config e.g. '2BHK':
SELECT COUNT(DISTINCT rs.RESalesID) AS UnitsSold
FROM ReSales rs
INNER JOIN REUnitDetails rud
    ON rud.REAssetId = rs.REAssetId
   AND rud.UniqueKey = rs.REUnitDetailId
WHERE rs.BookingDate IS NOT NULL
  AND rud.Configuration ILIKE '%2BHK%';""",
"""Canonical SQL for sales velocity (fastest/slowest selling project):
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
Keywords: velocity, fastest selling, slowest selling, sales rate,
units per month, sales speed, best performing, worst performing pace.
NEVER use EXTRACT(EPOCH). NEVER use only months.
Always use DAY + MONTH*30 + YEAR*365 formula.""",
"""Key aggregation patterns summary:
- Units sold        = COUNT(DISTINCT rs.RESalesID) — NO BookingDate filter
- Total sales value = COALESCE(SUM(rus.Amount), 0) with REPriceHeaders 'Sale Value' join
- Avg unit price    = AVG(rus.Amount) with REPriceHeaders 'Sale Value' join
- Balance recv.     = SUM(rus.Amount) - SUM(rus.Collections::numeric)
- Monthly trend     = DATE_TRUNC('month', rs.BookingDate) GROUP BY
- Sales velocity    = COUNT(DISTINCT rs.ReSalesID) / NULLIF(days_formula, 0) * 30 where days = DAY + MONTH*30 + YEAR*365 from AGE()
- Config filter     = JOIN REUnitDetails ON UniqueKey = REUnitDetailId, filter rud.Configuration ILIKE
- Developer rank    = GROUP BY ra.DeveloperName with LEFT JOIN REAssets""",
]


def _build_index():
    global _model, _index, _documents
    file_chunks: list[str] = []
    if os.path.exists(_SCHEMA_FILE):
        with open(_SCHEMA_FILE) as f:
            raw = f.read()
        file_chunks = [d.strip() for d in raw.split("\n\n") if d.strip()]

    _documents = _HARDCODED_CHUNKS + file_chunks

    try:
        from sentence_transformers import SentenceTransformer
        import faiss

        _model = SentenceTransformer(_MODEL_NAME)
        embeddings = _model.encode(_documents, show_progress_bar=False)
        dim = embeddings.shape[1]
        _index = faiss.IndexFlatL2(dim)
        _index.add(np.array(embeddings, dtype="float32"))
        print(f"[RAG] FAISS index built with {len(_documents)} chunks.")

    except ImportError as e:
        # FAISS not available — fall back to returning all chunks
        # retrieve_schema() will return everything when _index is None
        print(f"[RAG] FAISS not available ({e}) — using full chunk fallback.")

    except Exception as e:
        print(f"[RAG] Index build failed ({e}) — using full chunk fallback.")


_build_index()


def retrieve_schema(question: str, top_k: int = _TOP_K) -> str:
    if _index is None or _model is None:
        return "\n\n".join(_documents)
    q_emb = _model.encode([question])
    _, indices = _index.search(np.array(q_emb, dtype="float32"), top_k)
    selected = [_documents[i] for i in indices[0] if i < len(_documents)]
    return "\n\n".join(selected)