# RE Insight — Real Estate SQL Agent

A natural-language-to-SQL agent for a PostgreSQL real estate portfolio database. Ask plain-English questions; get structured answers backed by live data.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Running the API Server](#running-the-api-server)
- [Integrating as a Module](#integrating-as-a-module)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [How the Agent Works](#how-the-agent-works)
- [Example Questions](#example-questions)

---

## Overview

RE Insight translates plain-English questions into PostgreSQL queries and returns formatted answers. It is built on:

- **FastAPI** — REST API layer
- **Groq (LLaMA 3.3 70B)** — SQL generation via LLM
- **FAISS + sentence-transformers** — RAG-based schema retrieval so only relevant schema chunks are sent to the LLM
- **psycopg2** — PostgreSQL connection pool
- **PostgreSQL** — underlying real estate database

---

## Architecture

```
User question
     │
     ▼
sql_agent_module.answer()          ← public integration surface
     │
     ├─► rag.retrieve_schema()     ← FAISS vector search over schema chunks
     │                               returns top-K relevant schema paragraphs
     │
     ├─► sql_agent._call_llm()     ← sends system prompt + schema + question to Groq
     │                               returns raw SQL
     │
     ├─► db.run_query()            ← executes SQL against PostgreSQL
     │
     ├─► _diagnose_null_result()   ← if result is NULL/0, runs targeted diagnostics
     │                               and feeds them back to the LLM for self-correction
     │
     └─► _format_result()          ← formats raw rows (Crore/Lakh/plain number)
```

The retry loop runs up to **4 times**: on each failure or suspicious zero result it appends the error/diagnostic as a new user turn and asks the LLM to self-correct.

---

## Project Structure

```
.
├── app.py                  # FastAPI application (routes, CORS, health check)
├── sql_agent.py            # LLM call, retry loop, diagnostic helper
├── sql_agent_module.py     # ★ Clean integration module (use this in other projects)
├── explorer_v2.py          # Dynamic table explorer API (/explorer/*)
├── rag.py                  # FAISS index + schema chunk retrieval
├── db.py                   # psycopg2 connection pool + run_query()
├── schema.txt              # (optional) raw schema file — supplements hardcoded chunks
├── .env                    # environment variables (never commit)
└── README.md
```

---

## Setup

### 1. Clone and install dependencies

```bash
pip install fastapi uvicorn psycopg2-binary python-dotenv groq \
            sentence-transformers faiss-cpu numpy
```

### 2. Create a `.env` file

```env
DB_HOST=localhost
DB_NAME=test1
DB_USER=postgres
DB_PASSWORD=your_password_here

GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile   # optional, this is the default
```

### 3. Verify database connectivity

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
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model to use |

---

## Running the API Server

```bash
uvicorn app:app --reload --port 8000
```

Health check: `GET http://localhost:8000/health`

---

## Integrating as a Module

`sql_agent_module.py` is the clean integration surface. Copy it (along with `sql_agent.py`, `rag.py`, `db.py`, and optionally `schema.txt`) into your project.

```python
from sql_agent_module import answer

# Ask a question
result = answer("What are the total sales in Prabadevi Address?")

print(result.success)      # True / False
print(result.formatted)    # "Rs 12.34 Cr"
print(result.sql)          # the generated PostgreSQL query
print(result.raw)          # list[list] — raw DB rows
print(result.duration_ms)  # wall-clock time in ms
print(result.error)        # None on success, error string on failure

# Convert to dict (e.g. for JSON serialisation)
print(result.to_dict())
```

### AgentResult fields

| Field | Type | Description |
|---|---|---|
| `question` | `str` | The original question |
| `sql` | `str` | Generated SQL query |
| `raw` | `list[list]` | Raw rows from the database |
| `formatted` | `str` | Human-readable answer (Cr/L formatting) |
| `duration_ms` | `int` | Total time including LLM + DB |
| `error` | `str \| None` | Error message, or `None` on success |
| `success` | `bool` (property) | `True` when `error is None` |

### Minimal integration example

```python
from sql_agent_module import answer

questions = [
    "What are the balance receivables in Prabadevi Address?",
    "Which asset has the least sales?",
    "Which region has the highest receivables?",
]

for q in questions:
    r = answer(q)
    if r.success:
        print(f"Q: {q}\nA: {r.formatted}\n")
    else:
        print(f"Q: {q}\nERROR: {r.error}\n")
```

### CLI smoke-test

```bash
python sql_agent_module.py "What is the area sold in Goa Villas?"
```

---

## API Reference

### `POST /ask`

Ask a natural-language question.

**Request**
```json
{ "question": "What are the total sales in Prabadevi Address?" }
```

**Response**
```json
{
  "question":         "What are the total sales in Prabadevi Address?",
  "sql":              "SELECT COALESCE(SUM(rus.Amount), 0) ...",
  "result":           [[123456789.0]],
  "formatted_result": "Rs 12.35 Cr",
  "duration_ms":      1842
}
```

---

### `POST /run-sql`

Run a raw SQL query directly (useful for verification).

**Request**
```json
{ "sql": "SELECT COUNT(*) FROM REAssets" }
```

**Response**
```json
{
  "result":           [[42]],
  "formatted_result": "42"
}
```

---

### `GET /explorer/tables`

List all browsable tables with their columns, filter options, and capabilities.

---

### `GET /explorer/data/{table}`

Browse table data with pagination, sorting, filtering, and search.

**Query parameters**

| Parameter | Default | Description |
|---|---|---|
| `page` | `1` | Page number |
| `page_size` | `25` | Rows per page (max 200) |
| `sort_col` | `""` | Column to sort by |
| `sort_dir` | `"asc"` | `asc` or `desc` |
| `search` | `""` | Full-text search across searchable columns |
| `date_from` / `date_to` | `""` | Date range filter (ISO 8601) |
| `amount_min` / `amount_max` | `null` | Amount range filter |
| `filter_AssetName` | `""` | Filter by asset name |
| `filter_ZoneName` | `""` | Filter by zone |
| `filter_Scheme` | `""` | Filter by scheme |

---

### `GET /explorer/filter-options/{table}`

Returns dropdown values for all filterable columns in a table.

---

### Debug Endpoints

| Endpoint | Description |
|---|---|
| `GET /debug/assets?search=Goa` | Find exact asset names in the DB |
| `GET /debug/price-headers?asset_id=5` | Inspect REPriceHeaders for an asset |
| `GET /debug/sales-check?asset_name=Prabadevi` | Full diagnostic join check for an asset |
| `GET /health` | Liveness check |

---

## Database Schema

```
ZoneDetails       ZoneID, ZoneName
Regions           RegionsId, ZoneID, RegionsName
Locations         LocationId, ZoneID, RegionsId, LocationName
REAssets          REAssetId, AssetName, DeveloperName, BorrowerName,
                  ZoneId → ZoneDetails, RegionsId → Regions, LocationId → Locations
REUnitDetails     REUnitDetailId, REAssetId, ProjectName, DevelopmentType,
                  ProjectType, Wing, Floor, UnitNumber, Configuration,
                  AreaConsidered, AreaConsideredMeasurement, UniqueKey
REPriceHeaders    REPriceHeaderId, REAssetID → REAssets, ValueType, HeaderValue
ReSales           ReSalesID, REAssetId → REAssets, REUnitDetailId (varchar → UniqueKey),
                  CustomerName, BookingDate, RegistrationDate, Scheme, Financer
REUnitSales       REUnitSalesID, ReSalesID → ReSales, PriceHeader,
                  Amount (float), Demand (money), Collections (money)
```

**Key join for sales value queries:**
```sql
FROM ReSales rs
INNER JOIN REUnitSales rus ON rus.ReSalesID = rs.ReSalesID
INNER JOIN REPriceHeaders rph
    ON  rph.REAssetID   = rs.REAssetId
    AND rph.HeaderValue = rus.PriceHeader
    AND rph.ValueType   = 'Sale Value'
```

**Money columns must be cast before arithmetic:**
```sql
SUM(rus.Collections::numeric)   -- ✓ correct
SUM(rus.Collections)            -- ✗ will fail (money type)
```

---

## How the Agent Works

1. **RAG retrieval** — the question is embedded and compared against pre-indexed schema chunks using FAISS. The top 8 most relevant chunks are included in the LLM prompt, keeping token usage low while ensuring the model has the right context.

2. **SQL generation** — Groq's LLaMA 3.3 70B receives a detailed system prompt (canonical join patterns, column types, ILIKE rules) plus the retrieved schema and the question. It returns raw SQL.

3. **Execution** — the SQL runs against PostgreSQL via a connection pool.

4. **Self-correction loop** — if the result is NULL or zero, a diagnostic function queries the database to check: Does the asset exist? Does it have a `Sale Value` in REPriceHeaders? Are there any REUnitSales rows? These findings are fed back to the LLM as a new user turn, and it retries up to 4 times total.

5. **Formatting** — the raw rows are formatted using Indian currency conventions (Crore / Lakh).

---

## Example Questions

```
What are the total sales in Prabadevi Address?
What are the balance receivables in Prabadevi Address?
Which assets are located in the North zone?
What is the area sold in Goa Villas?
Which asset has the least sales?
Which region has the highest receivables?
How many units have been sold in [Asset Name]?
What is the ratio of commercial to residential sales?
```