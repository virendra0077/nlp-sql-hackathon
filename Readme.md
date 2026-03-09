# Real Estate SQL Agent — Backend

A natural-language-to-SQL agent for a PostgreSQL real estate portfolio database.  
Ask plain-English questions via REST API and get structured answers backed by live data.

---

## Table of Contents

- [Project Structure](#project-structure)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Running the Server](#running-the-server)
- [API Reference](#api-reference)
  - [POST /ask](#post-ask)
  - [POST /run-sql](#post-run-sql)
  - [GET /explorer/tables](#get-explorertables)
  - [GET /explorer/filter-options/{table}](#get-explorerfilter-optionstable)
  - [GET /explorer/data/{table}](#get-explorerdatatable)
  - [Debug Endpoints](#debug-endpoints)
  - [GET /health](#get-health)
- [Database Schema](#database-schema)
- [How the Agent Works](#how-the-agent-works)
- [Example Questions](#example-questions)

---

## Project Structure

```
.
├── app.py          # FastAPI application — routes and server entry point
├── sql_agent.py    # LLM call, retry loop, self-correction diagnostics
├── explorer_v2.py  # Dynamic table explorer API (/explorer/*)
├── rag.py          # FAISS vector index + schema chunk retrieval
├── db.py           # psycopg2 connection pool + run_query()
├── schema.txt      # (optional) raw schema supplement for RAG
└── .env            # environment variables — never commit this file
```

---

## Setup

### 1. Install dependencies

```bash
pip install fastapi uvicorn psycopg2-binary python-dotenv groq \
            sentence-transformers faiss-cpu numpy
```

### 2. Create a `.env` file in the project root

```env
DB_HOST=localhost
DB_NAME=test1
DB_USER=postgres
DB_PASSWORD=your_postgres_password

GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile
```

### 3. Verify the database connection

```bash
python - <<'EOF'
from db import run_query
print(run_query("SELECT COUNT(*) FROM REAssets"))
EOF
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DB_HOST` | No | `localhost` | PostgreSQL host |
| `DB_NAME` | No | `test1` | Database name |
| `DB_USER` | No | `postgres` | Database user |
| `DB_PASSWORD` | **Yes** | — | Database password |
| `GROQ_API_KEY` | **Yes** | — | Groq API key |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model used for SQL generation |

---

## Running the Server

```bash
uvicorn app:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

---

## API Reference

### POST /ask

Convert a natural-language question into SQL, execute it, and return the raw result.

**Request body**
```json
{
  "question": "What are the total sales in Prabadevi Address?"
}
```

**Response**
```json
{
  "question":    "What are the total sales in Prabadevi Address?",
  "sql":         "SELECT COALESCE(SUM(rus.Amount), 0) AS TotalSales FROM ReSales rs ...",
  "result":      [[123456789.0]],
  "duration_ms": 1842
}
```

| Field | Type | Description |
|---|---|---|
| `question` | string | The original question |
| `sql` | string | The generated PostgreSQL query |
| `result` | `list[list]` | Raw rows returned by the database |
| `duration_ms` | int | Total wall-clock time in milliseconds |

**Error response** (HTTP 400 / 500)
```json
{ "detail": "SQL generation failed after 4 attempts. Last error: ..." }
```

---

### POST /run-sql

Execute a raw SQL query directly against the database. Useful for verification and testing.

**Request body**
```json
{
  "sql": "SELECT COUNT(*) FROM REAssets"
}
```

**Response**
```json
{
  "result": [[42]]
}
```

---

### GET /explorer/tables

List all browsable tables with their columns and capabilities.

**Response**
```json
{
  "REAssets": {
    "display_cols": ["REAssetId", "AssetName", "DeveloperName", ...],
    "filterable":   ["ZoneName"],
    "has_date":     false,
    "has_amount":   false,
    "sum_cols":     [],
    "count_label":  "Assets"
  },
  ...
}
```

---

### GET /explorer/filter-options/{table}

Returns dropdown values for all filterable columns in a given table.

**Example**
```
GET /explorer/filter-options/RESales
```

**Response**
```json
{
  "AssetName": ["Goa Villas", "Prabadevi Address", ...],
  "Scheme":    ["Scheme A", "Scheme B", ...]
}
```

---

### GET /explorer/data/{table}

Browse table data with pagination, sorting, search, and filtering.

**Example**
```
GET /explorer/data/RESales?page=1&page_size=25&search=John&filter_AssetName=Goa+Villas
```

**Query parameters**

| Parameter | Default | Description |
|---|---|---|
| `page` | `1` | Page number (≥ 1) |
| `page_size` | `25` | Rows per page (1–200) |
| `sort_col` | `""` | Column name to sort by |
| `sort_dir` | `"asc"` | Sort direction: `asc` or `desc` |
| `search` | `""` | Full-text ILIKE search across searchable columns |
| `date_from` | `""` | Start of date range (ISO 8601, tables with date columns only) |
| `date_to` | `""` | End of date range (ISO 8601) |
| `amount_min` | `null` | Minimum amount filter (tables with amount columns only) |
| `amount_max` | `null` | Maximum amount filter |
| `filter_AssetName` | `""` | Filter by asset name |
| `filter_ZoneName` | `""` | Filter by zone name |
| `filter_Scheme` | `""` | Filter by scheme |
| `filter_PriceHeader` | `""` | Filter by price header |
| `filter_ValueType` | `""` | Filter by value type |
| `filter_DevelopmentType` | `""` | Filter by development type |
| `filter_AreaConsideredMeasurement` | `""` | Filter by area unit |

**Response**
```json
{
  "columns":     ["RESalesID", "AssetName", "CustomerName", ...],
  "rows":        [["1", "Goa Villas", "John Doe", ...]],
  "total":       350,
  "page":        1,
  "page_size":   25,
  "total_pages": 14,
  "stats":       {},
  "count_label": "Sales"
}
```

---

### Debug Endpoints

These endpoints help diagnose data issues and verify joins before querying.

#### GET /debug/assets

List all asset names in the database, with optional search.

```
GET /debug/assets
GET /debug/assets?search=Goa
```

**Response**
```json
[
  { "id": 3, "name": "Goa Villas" },
  { "id": 7, "name": "Goa Sea View" }
]
```

---

#### GET /debug/price-headers

Inspect REPriceHeaders rows for a specific asset — useful to verify whether `Sale Value` exists.

```
GET /debug/price-headers
GET /debug/price-headers?asset_id=5
```

**Response**
```json
[
  { "id": 12, "asset_id": 5, "value_type": "Sale Value", "header_value": "Base Price" }
]
```

---

#### GET /debug/sales-check

Full diagnostic join check for a named asset — shows asset ID, value types, row counts, and raw sum.

```
GET /debug/sales-check?asset_name=Prabadevi
```

**Response**
```json
{
  "asset":          "Prabadevi Address",
  "asset_id":       4,
  "value_types":    ["Sale Value", "GST"],
  "resales_count":  120,
  "reunit_count":   118,
  "raw_sum_amount": 98000000.0
}
```

---

### GET /health

Liveness check.

```
GET /health
```

**Response**
```json
{ "status": "ok" }
```

---

## Database Schema

```
ZoneDetails       ZoneID (PK), ZoneName

Regions           RegionsId (PK), ZoneID (FK → ZoneDetails), RegionsName

Locations         LocationId (PK), ZoneID, RegionsId, LocationName

REAssets          REAssetId (PK), AssetName, DeveloperName, BorrowerName,
                  ZoneId (FK → ZoneDetails.ZoneID),
                  RegionsId (FK → Regions.RegionsId),
                  LocationId (FK → Locations.LocationId), Address

REUnitDetails     REUnitDetailId (PK), REAssetId (FK), ProjectName,
                  DevelopmentType, ProjectType, Wing, Floor, UnitNumber,
                  Configuration, AreaConsidered (float),
                  AreaConsideredMeasurement ('Sq Ft' | 'Sq mtr' | 'Sq yards'),
                  UniqueKey (varchar)

REPriceHeaders    REPriceHeaderId (PK), REAssetID (FK → REAssets),
                  ValueType (e.g. 'Sale Value'), HeaderValue

ReSales           ReSalesID (PK), REAssetId (FK → REAssets),
                  REUnitDetailId (varchar FK → REUnitDetails.UniqueKey),
                  CustomerName, BookingDate, RegistrationDate,
                  Scheme, Financer, MISDate

REUnitSales       REUnitSalesID (PK), ReSalesID (FK → ReSales),
                  PriceHeader, Amount (float),
                  Demand (money), Collections (money)
```

### Key join for sales value queries

```sql
FROM ReSales rs
INNER JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
INNER JOIN REPriceHeaders rph
    ON  rph.REAssetID   = rs.REAssetId
    AND rph.HeaderValue = rus.PriceHeader
    AND rph.ValueType   = 'Sale Value'
```

### Money column casting (required)

```sql
-- Collections and Demand are PostgreSQL money type — must cast before arithmetic
SUM(rus.Collections::numeric)   -- correct
SUM(rus.Collections)            -- will fail
```

---

## How the Agent Works

### 1. RAG — Schema retrieval

When a question arrives, it is embedded using `sentence-transformers` (`all-MiniLM-L6-v2`) and compared against a FAISS index of pre-written schema chunks. The top 8 most relevant chunks are injected into the LLM prompt. This keeps token usage low while giving the model exactly the table/column knowledge it needs.

### 2. SQL generation

The LLM (Groq — LLaMA 3.3 70B) receives a detailed system prompt containing canonical join patterns, column type rules, ILIKE conventions, and area conversion formulas, followed by the retrieved schema chunks and the user's question. It returns a raw PostgreSQL query.

### 3. Execution

The query runs against PostgreSQL via a connection pool (`psycopg2`). Results are returned as raw rows.

### 4. Self-correction retry loop (up to 4 attempts)

If the query raises a PostgreSQL error, the error is appended to the conversation and the LLM is asked to fix the SQL.

If the query returns NULL or zero (which may indicate a bad join), a diagnostic function runs targeted checks:
- Does the asset name match anything in `REAssets`?
- Does `REPriceHeaders` contain a `Sale Value` row for this asset?
- Are there any `REUnitSales` rows joined to `ReSales` for this asset?

These findings are fed back to the LLM as a new user turn, and it retries with corrected SQL.

---

## Example Questions

```
What are the total sales in Prabadevi Address?
What are the balance receivables in Prabadevi Address?
Which assets are located in the North zone?
What is the area sold in Goa Villas?
Which asset has the least sales?
Which region has the highest receivables?
How many units have been sold in Goa Villas?
What is the ratio of commercial to residential sales?
```