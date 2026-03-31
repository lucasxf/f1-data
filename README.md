# F1 Analytics

Natural language queries and on-demand charts over live Formula 1 telemetry, powered by Metabase OSS and the Open F1 API.

> Portfolio project built for a Metabase backend engineering interview.

<!-- Add screenshot/gif here -->

---

## What it does

Ask a question in plain English and get an answer backed by real race data:

- **"Who had the top speed at Suzuka in 2026?"** → *Nico Hülkenberg (Audi) — 349 km/h*
- **"Top 10 lap times at Suzuka, fastest first"** → renders an embedded Metabase chart

The backend translates natural language into SQL using Metabase's built-in LLM endpoint, executes it against a PostgreSQL database populated from the Open F1 API, and either returns a plain-text answer or an embeddable Metabase chart URL.

---

## Tech stack

| Layer | Technology | Purpose |
|---|---|---|
| Data source | Open F1 API | Live F1 telemetry (laps, drivers, car data) |
| Database | PostgreSQL 15 | F1 data warehouse + Metabase app DB |
| Analytics | Metabase OSS | SQL generation, chart rendering, public embeds |
| Backend | Python 3.12 / FastAPI | Data ingestion orchestrator + API |
| Frontend | React 18 / Vite | Chat UI with Ask and Chart modes |
| Infrastructure | Docker Compose | Postgres + Metabase + Backend |

---

## Architecture

```
Docker Compose
+------------------------------------------------------------+
|                                                            |
|  postgres:5432          metabase:3000      backend:8080    |
|  [PostgreSQL 15]  <-->  [Metabase OSS] <-- [Python/FastAPI]|
|  - f1_data schema       - LLM SQL gen      - /api/ask     |
|  - metabase app db      - Public embeds     - /api/chart   |
|                                             - /api/ingest  |
+------------------------------------------------------------+
       ^                                         |
       |                                         v
  [Open F1 API]                         [React Frontend :5173]
  api.openf1.org                         (local dev server)
```

---

## Prerequisites

- **Docker Desktop** (with the Linux engine running)
- **Node.js 22+**
- **Anthropic API key** — get one at console.anthropic.com (used by Metabase's LLM SQL generation; costs ~$0.01/query with Claude Haiku)

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/lucasxf/f1-data.git
cd f1-data

# 2. Configure environment
cp .env.example .env
# Edit .env and fill in ANTHROPIC_API_KEY and your Metabase admin credentials

# 3. Start infrastructure
docker compose up -d

# 4. Wait ~60s for Metabase to initialize, then complete the setup wizard at:
#    http://localhost:3000
#    Use the same email/password you put in .env (MB_ADMIN_EMAIL / MB_ADMIN_PASSWORD)

# 5. Ingest race data (Suzuka 2026 Race)
curl -s -X POST http://localhost:8080/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"circuit": "Suzuka", "year": 2026, "session_type": "Race"}'

# 6. Start the frontend
cd frontend
npm install
npm run dev

# 7. Open http://localhost:5173
```

---

## API reference

All endpoints are served by the FastAPI backend on port 8080.

| Method | Path | Request body | Response |
|--------|------|-------------|----------|
| `GET` | `/health` | — | `{"status": "ok"}` |
| `GET` | `/api/sessions` | — | List of ingested sessions |
| `POST` | `/api/ingest` | `{"circuit": str, "year": int, "session_type": str}` | `{"session_key": int, "rows": {...}}` |
| `POST` | `/api/ask` | `{"question": str}` | `{"answer": [rows], "sql": str}` |
| `POST` | `/api/chart` | `{"prompt": str}` | `{"embed_url": str, "sql": str}` |

**Ingest a session before querying it.** The `circuit` value must match the Open F1 API's `circuit_short_name` (e.g. `"Suzuka"`, `"Melbourne"`, `"Monza"`).

---

## Database schema

All tables live in the `f1_data` schema in PostgreSQL.

| Table | Description |
|---|---|
| `sessions` | Race/qualifying session metadata (circuit, year, date) |
| `drivers` | Driver roster per session (name, team, number) |
| `laps` | Per-lap timing data (duration, sector splits, speed traps) |
| `top_speeds` | Pre-aggregated max speed per driver per session (avoids ingesting 585K raw telemetry rows) |

---

## Project structure

```
f1-data/
├── docker-compose.yml        # postgres + metabase + backend
├── .env.example              # copy to .env and fill in secrets
├── infra/
│   └── init.sql              # f1_data schema (auto-runs on first postgres boot)
├── backend/
│   ├── main.py               # FastAPI app: endpoints + Metabase orchestration
│   ├── openf1.py             # Open F1 API client
│   ├── db.py                 # PostgreSQL helpers (upsert, queries)
│   ├── metabase_client.py    # Metabase REST API (auth, LLM SQL, cards, embeds)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/App.tsx           # React UI: Ask + Chart modes
│   └── vite.config.ts        # Proxies /api to localhost:8080
└── docs/
    └── architecture-plan.md  # Detailed architecture decisions and rationale
```

---

## How it works

### NL Query (Ask mode)
1. User submits a question ("Who had the top speed at Suzuka?")
2. Backend calls Metabase's OSS BYOK endpoint `POST /api/llm/generate-sql` with the question and references to the `f1_data` tables
3. Metabase generates SQL via Anthropic's API
4. Backend executes the SQL against PostgreSQL via Metabase's `POST /api/dataset`
5. Result rows are returned as JSON and rendered as a table in the UI

### Chart (Chart mode)
1. Same flow as above through SQL generation
2. Backend creates a Metabase saved question (card) via `POST /api/card`
3. Backend enables public sharing via `POST /api/card/{id}/public_link`
4. Frontend receives a `localhost:3000/public/question/{uuid}` URL and renders it in an `<iframe>`

---

## Built with

- [Open F1 API](https://openf1.org) — free, open-source F1 telemetry API
- [Metabase OSS](https://github.com/metabase/metabase) — open-source analytics platform
- [FastAPI](https://fastapi.tiangolo.com) — Python web framework
- [React](https://react.dev) + [Vite](https://vite.dev) — frontend
