# 🏢 RE Insight — Real Estate Intelligence

> **Natural Language → SQL for Real Estate Portfolio Analytics**  
> Ask questions about your portfolio in plain English. RE Insight generates the SQL, runs it, and gives you instant answers.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Railway-6366f1?style=for-the-badge&logo=railway)](https://hackathon1-production-89cd.up.railway.app/login/?next=/)
[![GitHub](https://img.shields.io/badge/GitHub-Repo-181717?style=for-the-badge&logo=github)](https://github.com/virendra0077/nlp-sql-hackathon.git)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python)](https://python.org)
[![Django](https://img.shields.io/badge/Django-4.x-092E20?style=for-the-badge&logo=django)](https://djangoproject.com)

---

## 📸 Preview

| SQL Chat | Data Explorer |
|---|---|
| Ask questions in plain English and get instant answers | Browse, filter, sort and paginate all database tables |

---

## 🚀 Live Demo

| | |
|---|---|
| **URL** | https://hackathon1-production-89cd.up.railway.app/login/?next=/ |
| **Username** | `admin` |
| **Password** | `admin@123` |

---

## 💡 What It Does

RE Insight is a full-stack AI-powered dashboard that lets real estate analysts query their portfolio database using plain English. No SQL knowledge required.

**Example questions you can ask:**
- *"What are the sales in Prabadevi Address?"* → `₹2,056.12 Cr`
- *"What are the balance receivables in Prabadevi Address?"* → `₹1,431.57 Cr`
- *"Which assets are located in the North?"* → `Lakshmi Nagar Apartments`
- *"What is the area sold in Goa Villas?"* → `12,150 Sq Ft`
- *"Which region has the highest receivables?"*
- *"What is the sales velocity of each asset?"*
- *"How many 2 BHK units were sold?"*

---

## ✨ Features

### 🤖 AI SQL Chat
- **Natural Language to SQL** — powered by Groq's LLaMA 3.3 70B model
- **Auto-correction** — if a query returns `NULL` or fails, the agent self-diagnoses and retries up to 4 times
- **Multi-key rotation** — seamlessly rotates across multiple Groq API keys when rate limits are hit
- **RAG-powered schema retrieval** — FAISS + SentenceTransformers fetches the most relevant schema chunks for each query
- **Casual conversation guard** — greetings and small talk are handled gracefully without triggering SQL generation

### 🎙️ Voice Input
- Speak your question using the microphone button (Web Speech API)
- Supports English (India) locale
- Auto-submits after detecting final speech

### 📊 Data Explorer
- Browse all 8 database tables visually
- Filter, sort, and search across any column
- Date range and amount range filters
- Pagination with configurable page size (25 / 50 / 100 rows)
- Aggregated stats (total rows, sum of amounts) shown in real time

### 🔐 Auth & Security
- Django session-based authentication
- All routes protected by `login_required`
- CSRF protection on all POST endpoints
- Secure session cookies (HTTPS in production)

---

## 🗄️ Database Schema

```
ZoneDetails       → Geographic zones (North, South, East, West)
Regions           → Sub-divisions within zones
Locations         → Further subdivision within regions
REAssets          → Master table of real estate assets / projects
REUnitDetails     → Individual units / apartments within an asset
REPriceHeaders    → Price header labels mapped to ValueTypes per asset
RESales           → One row per sale transaction
REUnitSales       → Financial breakdown of each sale (Amount, Demand, Collections)
```

### Key Relationships
```
ZoneDetails ──< REAssets ──< RESales ──< REUnitSales
                    └──< REUnitDetails
                    └──< REPriceHeaders
Regions     ──< REAssets
Locations   ──< REAssets
```

---

## 🧠 How the AI Works

```
User Question
     │
     ▼
┌─────────────────────┐
│  Casual detector    │  ← Small talk? Return canned response.
└─────────────────────┘
     │ No
     ▼
┌─────────────────────┐
│  FAISS RAG          │  ← Retrieve top-12 schema chunks via vector similarity
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│  Groq LLM           │  ← System prompt + schema context + question → SQL
│  (LLaMA 3.3 70B)    │
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│  Run on PostgreSQL  │
└─────────────────────┘
     │
     ▼
  NULL / Error?
     │ Yes
     ▼
┌─────────────────────┐
│  Self-diagnosis     │  ← Check asset names, ValueTypes, join counts
│  + LLM re-query     │  ← Feed diagnostics back to LLM, retry (max 4x)
└─────────────────────┘
     │
     ▼
  Formatted Result → User
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Django 4.x (Python 3.11+) |
| **Database** | PostgreSQL (psycopg2 connection pool) |
| **LLM** | Groq API — LLaMA 3.3 70B Versatile |
| **Vector Search** | FAISS + SentenceTransformers (`all-MiniLM-L6-v2`) |
| **Frontend** | Vanilla JavaScript, custom dark UI |
| **Fonts** | Cabinet Grotesk, Fira Code, DM Sans |
| **Auth** | Django built-in auth + bcrypt password hashing |
| **Hosting** | Railway |
| **Static Files** | WhiteNoise |

---

## 📁 Project Structure

```
nlp-sql-hackathon/
├── manage.py
├── db.py                    # PostgreSQL connection pool (psycopg2)
├── sql_agent.py             # LLM orchestration, key rotation, self-correction
├── rag.py                   # FAISS vector search for schema retrieval
├── schema.txt               # Optional extra schema chunks for RAG
│
├── re_insight/              # Django project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── agent/                   # SQL Chat app
│   ├── views.py             # /ask, /run-sql, /debug/* endpoints
│   └── urls.py
│
├── explorer/                # Data Explorer app
│   ├── views.py             # /explorer/tables, /explorer/data/<table>
│   └── urls.py
│
└── templates/
    ├── index.html           # SQL Chat UI
    ├── explorer.html        # Data Explorer UI
    └── login.html           # Sign-in page
```

---

## ⚙️ Local Setup

### Prerequisites
- Python 3.11+
- PostgreSQL
- Node.js (optional, for frontend tooling)

### 1. Clone the repository
```bash
git clone https://github.com/virendra0077/nlp-sql-hackathon.git
cd nlp-sql-hackathon
```

### 2. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate        # Linux / Mac
venv\Scripts\activate           # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
# Django
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# PostgreSQL
DB_HOST=localhost
DB_NAME=your_db_name
DB_USER=postgres
DB_PASSWORD=your_password
DB_PORT=5432

# Groq API Keys (add as many as you need for rotation)
GROQ_API_KEY_1=gsk_...
GROQ_API_KEY_2=gsk_...
GROQ_API_KEY_3=gsk_...

# Optional: override default model
GROQ_MODEL=llama-3.3-70b-versatile
```

### 5. Run Django migrations
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. Start the development server
```bash
python manage.py runserver
```

Visit `http://localhost:8000` and sign in.

---

## 🔑 Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | ✅ | Django secret key |
| `DEBUG` | ✅ | `True` for dev, `False` for prod |
| `DB_HOST` | ✅ | PostgreSQL host |
| `DB_NAME` | ✅ | Database name |
| `DB_USER` | ✅ | Database user |
| `DB_PASSWORD` | ✅ | Database password |
| `DB_PORT` | ✅ | PostgreSQL port (default: 5432) |
| `GROQ_API_KEY_1` | ✅ | Primary Groq API key |
| `GROQ_API_KEY_2..10` | ➕ | Additional keys for rotation |
| `GROQ_MODEL` | ➖ | LLM model name (default: `llama-3.3-70b-versatile`) |
| `DATABASE_URL` | ➖ | Full DB URL (overrides individual DB_* vars) |

---

## 🌐 Deployment (Railway)

1. Push your code to GitHub
2. Create a new Railway project and connect the GitHub repo
3. Add a PostgreSQL plugin in Railway
4. Set all environment variables in Railway's Variables tab
5. Railway auto-detects Django and deploys via `Procfile` or `railway.json`

```
# Procfile
web: gunicorn re_insight.wsgi --bind 0.0.0.0:$PORT
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | SQL Chat UI |
| `POST` | `/ask` | Submit a natural language question |
| `POST` | `/run-sql` | Execute raw SQL directly |
| `GET` | `/health` | Health check (no auth required) |
| `GET` | `/explorer/` | Data Explorer UI |
| `GET` | `/explorer/tables` | List all available tables + metadata |
| `GET` | `/explorer/filter-options/<table>` | Get filterable values for a table |
| `GET` | `/explorer/data/<table>` | Paginated, filtered table data |
| `GET` | `/debug/assets` | List assets (debug) |
| `GET` | `/debug/price-headers` | List price headers (debug) |
| `GET` | `/debug/sales-check` | Diagnose sales data for an asset (debug) |

### POST `/ask` — Example

**Request:**
```json
{
  "question": "What are the sales in Prabadevi Address?"
}
```

**Response:**
```json
{
  "question": "What are the sales in Prabadevi Address?",
  "sql": "SELECT COALESCE(SUM(rus.Amount), 0) AS TotalSales ...",
  "result": [[2056120000.0]],
  "formatted_result": "Rs 2,056.12 Cr",
  "duration_ms": 1243
}
```

---

## 🧩 SQL Generation Rules (System Prompt Highlights)

The LLM is given a detailed system prompt covering 17 rules, including:

- Always use `ILIKE` for text matching (never exact `=`)
- Cast `money` columns before arithmetic: `SUM(rus.Collections::numeric)`
- `COALESCE` every aggregate to avoid `NULL` returns
- Canonical join pattern for sales and receivables queries
- Area conversion: Sq Ft / Sq mtr / Sq yards → always normalized to Sq Ft
- Sales velocity formula using `AGE()` (never `EPOCH`)
- Unsold inventory using `LEFT JOIN` on `UniqueKey`
- Configuration filtering: always `ILIKE '%2 BHK%'` (space required)
- No `REPriceHeaders` join for zone/region/portfolio-wide aggregates

---

## 🏆 Hackathon Challenge Questions

| Question | Answer |
|---|---|
| Sales in Prabadevi Address | ₹2,056.12 Cr |
| Balance receivables in Prabadevi Address | ₹1,431.57 Cr |
| Assets in the North zone | Lakshmi Nagar Apartments |
| Area sold in Goa Villas | 12,150 Sq Ft |
| Asset with least sales | Queryable ✅ |
| Ratio of commercial to residential sales | Queryable ✅ |
| Poorest performing asset | Queryable ✅ |
| Region with highest receivables | Queryable ✅ |

---

## 👨‍💻 Author

**Virendra**  
GitHub: [@virendra0077](https://github.com/virendra0077)

---

## 📄 License

This project was built for the RE Insight Hackathon.  
All rights reserved © 2025.