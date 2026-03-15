# RE Insight — Real Estate Portfolio Intelligence Platform

A Django-based web application that lets you query a real estate portfolio database using natural language. Ask questions in plain English and get SQL-powered answers instantly, or explore the data visually through an interactive table explorer.

---

## Features

- **SQL Chat** — Ask questions in natural language, get answers backed by live PostgreSQL queries
- **Data Explorer** — Browse all tables with filtering, sorting, search, and pagination
- **Smart Retry Loop** — Auto-diagnoses failed or empty queries and regenerates SQL up to 4 times
- **Multi-Key Groq Rotation** — Automatically rotates across up to 10 Groq API keys when quota is hit
- **RAG-Powered Schema Retrieval** — FAISS vector search finds the most relevant schema context for each question
- **Indian number formatting** — Results displayed in ₹ Cr / ₹ L format

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 4.x |
| Database | PostgreSQL |
| LLM | Groq (`deepseek-r1-distill-llama-70b`) |
| Embeddings | `sentence-transformers` (all-MiniLM-L6-v2) |
| Vector Search | FAISS |
| DB Driver | psycopg2 |
| Frontend | Vanilla JS + custom CSS (no framework) |

---

## Project Structure

```
nlp_sql_hackathon/
│
├── manage.py
├── db.py                  # PostgreSQL connection pool (psycopg2)
├── sql_agent.py           # LLM SQL generation + Groq key rotation
├── rag.py                 # FAISS vector index + schema retrieval
├── schema.txt             # Optional extra schema chunks for RAG
│
├── agent/                 # SQL Chat app
│   ├── views.py           # /ask, /run-sql, /health, debug endpoints
│   └── urls.py
│
├── explorer/              # Data Explorer app
│   ├── views.py           # Table config + REST endpoints
│   └── urls.py
│
├── templates/
│   ├── index.html         # SQL Chat UI
│   └── explorer.html      # Data Explorer UI
│
└── .env                   # API keys and DB config (never commit this)
```

---

## Database Schema

```
ZoneDetails       ← geographic zones (North / East / West / South)
Regions           ← sub-divisions within zones
Locations         ← further subdivision within regions
REAssets          ← master table of real estate projects
REUnitDetails     ← individual units/apartments within an asset
REPriceHeaders    ← maps price header labels to value types per asset
RESales           ← one row per sale transaction
REUnitSales       ← financial breakdown of each sale (Amount, Demand, Collections)
```

**Key join paths:**
- `REAssets → ZoneDetails` via `ZoneId = ZoneID`
- `RESales → REAssets` via `REAssetId`
- `REUnitSales → ReSales` via `ReSalesID`
- `REUnitDetails → ReSales` via `UniqueKey = REUnitDetailId` (both varchar)
- `REPriceHeaders` joined on `REAssetID + HeaderValue + ValueType = 'Sale Value'`

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <your-repo-url>
cd nlp_sql_hackathon

pip install django psycopg2-binary groq python-dotenv \
            sentence-transformers faiss-cpu numpy
```

### 2. Configure environment variables

Create a `.env` file at the project root:

```env
# Database
DB_HOST=localhost
DB_NAME=your_database_name
DB_USER=postgres
DB_PASSWORD=your_password
DB_PORT=5432

# Groq API keys (rotates automatically when quota is hit)
GROQ_API_KEY_1=gsk_xxxxxxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY_2=gsk_yyyyyyyyyyyyyyyyyyyyyyyy
GROQ_API_KEY_3=gsk_zzzzzzzzzzzzzzzzzzzzzzzz

# Model selection
GROQ_MODEL=deepseek-r1-distill-llama-70b
```

> Get free Groq API keys at [console.groq.com](https://console.groq.com)

### 3. Set up the database

Run the SQL schema script to create all tables:

```bash
psql -U postgres -d your_database_name -f schema.sql
```

### 4. Run migrations and create a superuser

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Start the server

```bash
python manage.py runserver
```

Visit `http://localhost:8000` — log in with your superuser credentials.

---

## Usage

### SQL Chat (`/`)

Type a natural language question and get a formatted answer:

| Question | Answer |
|---|---|
| What are the sales in Prabadevi Address? | ₹ 2,056.12 Cr |
| What are the balance receivables in Prabadevi Address? | ₹ 1,431.57 Cr |
| Which assets are in the North zone? | Lakshmi Nagar Apartments |
| What is the area sold in Goa Villas? | 12,150 Sq Ft |
| How many 2 BHK units sold? | 42 |
| Which developer has the highest total sales? | ... |
| Show monthly sales trend | Table of month-wise data |
| Which region has the highest receivables? | ... |

### Data Explorer (`/explorer`)

- Click any table in the sidebar to browse its data
- Use the search bar, dropdowns, and date/amount range filters
- Click any column header to sort
- Stats strip shows total rows and sum of key financial columns

---

## How SQL Generation Works

```
User Question
      ↓
RAG: FAISS retrieves top-12 relevant schema chunks
      ↓
Groq LLM generates SQL (with 12-rule system prompt)
      ↓
Query runs against PostgreSQL
      ↓
Result is NULL or 0?
  YES → Diagnose (check asset names, ValueTypes, join counts)
        → Feed diagnostics back to LLM → regenerate (up to 4 retries)
  NO  → Format and return result
```

### Groq Key Rotation

```
Key #1 hits quota → instantly switch to Key #2
Key #2 hits quota → instantly switch to Key #3
Key #3 hits quota → wait for Groq's retry hint → reset to Key #1
```

Console output on rotation:
```
[sql_agent] Rotated to Groq key #2 (gsk_yyyy…)
```

---

## API Endpoints

| Method | URL | Description |
|---|---|---|
| `POST` | `/ask` | Natural language → SQL → formatted result |
| `POST` | `/run-sql` | Execute raw SQL directly |
| `GET` | `/health` | Health check (used by UI status indicator) |
| `GET` | `/debug/assets` | List all assets (optional `?search=`) |
| `GET` | `/debug/price-headers` | List price headers (optional `?asset_id=`) |
| `GET` | `/debug/sales-check` | Full diagnostic for an asset (`?asset_name=`) |
| `GET` | `/explorer/tables` | List all explorer table configs |
| `GET` | `/explorer/filter-options/<table>` | Get dropdown values for a table |
| `GET` | `/explorer/data/<table>` | Paginated, filtered, sorted table data |

---

## Configuration Tips

### Switching LLM model

In `.env`:
```env
# Best accuracy (chain-of-thought reasoning, recommended):
GROQ_MODEL=deepseek-r1-distill-llama-70b

# Fastest / highest daily limit:
GROQ_MODEL=llama-3.3-70b-versatile
```

### Adding more Groq keys

Just add numbered keys to `.env` — no code changes needed:
```env
GROQ_API_KEY_4=gsk_...
GROQ_API_KEY_5=gsk_...
```

### Extending the RAG schema

Add extra context to `schema.txt` (blank-line separated chunks) or add to `_HARDCODED_CHUNKS` in `rag.py`. The FAISS index rebuilds automatically on startup.

---

## Known Limitations

- All LLM queries are `SELECT` only — no write operations exposed
- The Data Explorer `FullView` table is a multi-join view and may return multiple rows per sale due to the `REUnitDetails` cross-join on `REAssetId`
- FAISS index is in-memory and rebuilds on every server restart (fast, ~1s)
- Groq free tier resets daily — all 3 keys exhausted means waiting for midnight UTC reset

---

## License

Internal hackathon project. Not licensed for public distribution.