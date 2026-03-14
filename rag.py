"""
rag.py — Schema retrieval via FAISS vector search.
Place at project root alongside manage.py.
"""

import os
import numpy as np

_TOP_K       = 8
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
LEFT JOIN REPriceHeaders rph
    ON rph.REAssetID = rs.REAssetId
   AND rph.HeaderValue = rus.PriceHeader
   AND rph.ValueType = 'Sale Value'
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
JOIN REPriceHeaders rph
    ON rph.REAssetID = rs.REAssetId
   AND rph.HeaderValue = rus.PriceHeader
   AND rph.ValueType = 'Sale Value'
GROUP BY rg.RegionsName
ORDER BY Receivables DESC
LIMIT 1;""",
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
    except ImportError:
        print("[RAG] faiss or sentence_transformers not installed — returning all chunks.")


_build_index()


def retrieve_schema(question: str, top_k: int = _TOP_K) -> str:
    if _index is None or _model is None:
        return "\n\n".join(_documents)
    q_emb = _model.encode([question])
    _, indices = _index.search(np.array(q_emb, dtype="float32"), top_k)
    selected = [_documents[i] for i in indices[0] if i < len(_documents)]
    return "\n\n".join(selected)