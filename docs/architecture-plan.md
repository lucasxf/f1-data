# F1 x Metabase Analytics MVP -- Architecture & Implementation Plan

## Context

Portfolio project for a Metabase backend engineering interview. Demonstrates Metabase's analytics capabilities (including its OSS AI features) using real Formula 1 telemetry from the Open F1 API. Two use cases drive the MVP:

1. **NL Query**: "Top speed at Suzuka on 29/03/2026?" -> text answer with driver + speed
2. **Prompt-to-Chart**: "Top 10 lap times, fastest first" -> rendered Metabase chart

The Suzuka 2026 Race (session_key=11253, meeting_key=1281) happened on 2026-03-29 and has full data: 22 drivers, lap timing, telemetry.

---

## 1. Database Selection

### Candidates

| DB | Fits Because | Trade-offs |
|----|-------------|------------|
| **PostgreSQL 15** | First-class Metabase support. Dual-duty: Metabase app DB + F1 data warehouse. Proven Docker pattern from Learnimo. Best LLM SQL generation dialect support. | Heavier than SQLite (but trivial in Docker). |
| **SQLite** | Zero infra -- just a file. Metabase can connect to it. | Can't be Metabase's app DB (needs H2). No concurrent writes. Weaker LLM SQL dialect support. Two DB engines in play. |
| **MySQL 8** | Metabase supports it as both app DB and warehouse. | No advantage over PostgreSQL. No existing Docker pattern. MySQL quirks. |

### Recommendation: PostgreSQL 15

Using `pgvector/pgvector:pg15` image (same as Learnimo). Single DB service for everything.

---

## 2. System Architecture

```
Docker Compose
+------------------------------------------------------------+
|                                                            |
|  postgres:5432          metabase:3000      backend:8080    |
|  [PostgreSQL 15]  <-->  [Metabase OSS] <-- [Python/FastAPI]|
|  - f1_data schema       - Metabot/LLM      - /api/ask     |
|  - metabase app db      - Public embeds     - /api/chart   |
|                         - REST API          - /api/ingest  |
+------------------------------------------------------------+
       ^                                         |
       |                                         v
  [Open F1 API]                         [React Frontend :5173]
  api.openf1.org                         (local dev server)
```

**Docker services (3):** postgres, metabase, backend
**Local process (1):** React frontend (Vite dev server)

**Communication:**
- Frontend -> Backend: REST (JSON)
- Backend -> Open F1 API: HTTP GET (data ingestion)
- Backend -> PostgreSQL: psycopg2 (write ingested data)
- Backend -> Metabase API: HTTP (LLM SQL gen, card creation, dataset queries)
- Metabase -> PostgreSQL: JDBC (query f1_data, store app state)

---

## 3. Open F1 Integration

### API Base URL

`https://api.openf1.org/v1/`

- No pagination -- all results returned at once
- Rate limit: 30 requests per 10 seconds
- Filtering: `?field=value`, `?field>=value`, `?session_key=latest`

### Endpoints per Use Case

**UC1 (top speed):**
- `GET /sessions?circuit_short_name=Suzuka&year=2026&session_name=Race` -> session_key=11253
- `GET /car_data?session_key=11253&speed>=300` -> filtered high-speed telemetry (server-side filter avoids 500K+ row download)
- `GET /drivers?session_key=11253` -> driver number-to-name mapping

**UC2 (lap times):**
- `GET /laps?session_key=11253` -> ~1,320 rows (22 drivers x 60 laps) -- manageable
- `GET /drivers?session_key=11253` -> name mapping

### Volume Management (Critical)

Raw car_data at 3.7Hz = ~22 * 7200 * 3.7 = **585K rows per race session**. We do NOT store raw car_data. Instead:
- Use server-side filter `speed>=250` to get a small subset
- Aggregate to **max speed per driver per session** = ~22 rows
- Store in `top_speeds` table

### DB Schema

```sql
CREATE SCHEMA f1_data;

CREATE TABLE f1_data.sessions (
    session_key INTEGER PRIMARY KEY,
    meeting_key INTEGER,
    circuit_short_name VARCHAR(50),
    country_name VARCHAR(100),
    year INTEGER,
    session_name VARCHAR(50),
    date_start TIMESTAMP
);

CREATE TABLE f1_data.drivers (
    id SERIAL PRIMARY KEY,
    session_key INTEGER REFERENCES f1_data.sessions(session_key),
    driver_number INTEGER,
    full_name VARCHAR(200),
    name_acronym VARCHAR(5),
    team_name VARCHAR(100),
    UNIQUE(session_key, driver_number)
);

CREATE TABLE f1_data.laps (
    id SERIAL PRIMARY KEY,
    session_key INTEGER REFERENCES f1_data.sessions(session_key),
    driver_number INTEGER,
    lap_number INTEGER,
    lap_duration FLOAT,
    duration_sector_1 FLOAT,
    duration_sector_2 FLOAT,
    duration_sector_3 FLOAT,
    i1_speed INTEGER,
    i2_speed INTEGER,
    st_speed INTEGER,
    is_pit_out_lap BOOLEAN DEFAULT FALSE,
    UNIQUE(session_key, driver_number, lap_number)
);

CREATE TABLE f1_data.top_speeds (
    id SERIAL PRIMARY KEY,
    session_key INTEGER REFERENCES f1_data.sessions(session_key),
    driver_number INTEGER,
    max_speed INTEGER,
    recorded_at TIMESTAMP,
    UNIQUE(session_key, driver_number)
);
```

### Ingestion Strategy

**On-demand.** When a user asks a question, the backend checks if the session data exists in PostgreSQL. If not, fetches from Open F1 and inserts. Also exposes `POST /api/ingest` for manual triggering.

- Rate limit: 30 req / 10 sec -- not a concern (3-4 calls per session ingestion)
- No pagination in Open F1 API -- all results in one response

---

## 4. Metabase Integration

### Connecting to PostgreSQL

Metabase uses PostgreSQL as its app DB via env vars (`MB_DB_TYPE=postgres`, `MB_DB_HOST=postgres`, etc.). The same PostgreSQL instance hosts the `f1_data` schema. On first Metabase sync, it auto-discovers the f1_data tables.

The f1_data warehouse connection is added either:
- Automatically via `POST /api/database` from the backend on startup
- Or manually in Metabase Admin > Databases

### UC1 Strategy: Metabase OSS BYOK `/api/llm/generate-sql`

Confirmed at `metabase/src/metabase/llm/api.clj` -- OSS endpoint that takes:
- `prompt`: natural language question
- `database_id`: Metabase's internal DB ID for the f1_data warehouse
- `referenced_entities`: table IDs (discovered via `GET /api/table`)

Returns generated SQL. Backend then executes via `POST /api/dataset` and formats the result as text.

**Requires:** Anthropic API key configured via `MB_LLM_ANTHROPIC_API_KEY` env var. This is acceptable -- CLAUDE.md says "free tools only (Metabase itself excepted)" and this is a Metabase feature.

**Fallback:** If LLM integration proves problematic, the backend can use hardcoded parameterized SQL queries (user selects session from dropdown, backend runs `SELECT d.full_name, ts.max_speed FROM ...`).

### UC2 Strategy: Public Embed via API

1. Backend calls `/api/llm/generate-sql` for the chart prompt
2. Backend creates a saved question via `POST /api/card` with the SQL + `display: "table"` or `"bar"`
3. Backend enables public sharing via `POST /api/card/{id}/public_link`
4. Returns public embed URL: `http://localhost:3000/public/question/{uuid}`
5. Frontend renders `<iframe src="...">` -- Metabase handles chart rendering

Public sharing is enabled by default in Metabase OSS.

### Authentication to Metabase API

Backend authenticates via `POST /api/session` with admin credentials on startup, caches the session token. Uses `X-Metabase-Session` header for all API calls.

---

## 5. Backend (Python / FastAPI)

### Why Python

- Open F1 project is Python -- familiar data models
- `requests` + `psycopg2` = minimal boilerplate for HTTP + SQL
- FastAPI gives auto-generated Swagger docs (good for demo)
- Data pipeline work (fetch, transform, insert) is a scripting task

### Endpoints

```
POST /api/ask
  Body: { "question": "Top speed at Suzuka on 29/03/2026?" }
  Returns: { "answer": "Max Verstappen (Red Bull Racing, #3) reached 342 km/h", "sql": "SELECT ..." }

POST /api/chart
  Body: { "prompt": "Top 10 lap times, fastest first" }
  Returns: { "embed_url": "http://localhost:3000/public/question/{uuid}" }

POST /api/ingest
  Body: { "circuit": "Suzuka", "year": 2026, "session_type": "Race" }
  Returns: { "session_key": 11253, "rows": { "laps": 1320, "top_speeds": 22, "drivers": 22 } }

GET /api/sessions
  Returns: list of available sessions (for frontend autocomplete)
```

### Responsibilities

Thin orchestrator:
1. Fetch Open F1 data -> insert to PostgreSQL
2. Forward NL queries to Metabase LLM endpoint
3. Execute SQL via Metabase dataset API
4. Create Metabase cards and manage public links
5. Format results for frontend

---

## 6. Frontend (Vite + React + TypeScript)

### Component Structure

```
App
  Header          -- title + project description
  ChatPanel
    ModeToggle    -- "Ask" (UC1) vs "Chart" (UC2) tabs
    ChatInput     -- text input + submit
    ChatResponse  -- text answer (UC1) or iframe (UC2)
  SessionInfo     -- shows current session context (optional)
```

### Integration

- UC1: `POST /api/ask` -> display `answer` as text
- UC2: `POST /api/chart` -> render `<iframe src={embed_url} width="100%" height="600" />`
- Two-mode UI avoids intent classification complexity

---

## 7. Implementation Plan

### Milestone 1: Infrastructure
**Docker Compose + PostgreSQL + Metabase**
- `docker-compose.yml` with postgres + metabase services
- `.env` / `.env.example` with all config vars
- `init.sql` with f1_data schema
- Verify Metabase starts and discovers f1_data tables
- Configure LLM API key
- **Deliverable:** `docker compose up` -> Metabase at localhost:3000 with empty f1_data tables

### Milestone 2: Data Ingestion
**Python backend + Open F1 client**
- FastAPI project with Dockerfile
- Open F1 client: fetch sessions, laps, drivers, car_data (filtered)
- `POST /api/ingest` endpoint
- Transform + insert to PostgreSQL (upsert)
- Add backend service to docker-compose.yml
- **Deliverable:** `/api/ingest` populates all 4 tables for Suzuka 2026
- **Depends on:** Milestone 1

### Milestone 3: NL Query (Use Case 1)
**Backend -> Metabase LLM -> dataset API**
- `POST /api/ask` endpoint
- Metabase API authentication (session token)
- Discover table IDs via `GET /api/table`
- Call `/api/llm/generate-sql` with prompt + table refs
- Execute SQL via `/api/dataset`
- Format result as natural language
- **Deliverable:** `curl POST /api/ask` returns text answer
- **Depends on:** Milestone 2

### Milestone 4: Chart Generation (Use Case 2)
**Backend -> Metabase card creation + public embed**
- `POST /api/chart` endpoint
- Create Metabase card via `/api/card`
- Enable public link via `/api/card/{id}/public_link`
- Return embed URL
- **Deliverable:** embed URL renders a working Metabase chart
- **Depends on:** Milestone 3

### Milestone 5: React Frontend
**Chat UI with two modes**
- Vite + React + TypeScript project
- ChatInput, ChatResponse, ModeToggle components
- Wire to `/api/ask` and `/api/chart`
- Display text answers and embedded charts
- **Deliverable:** full working MVP in browser
- **Depends on:** Milestone 4

---

## 8. Risks

| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| 1 | **Metabase LLM requires Anthropic API key** | Cost (~$0.01/query) technically violates "free tools" | CLAUDE.md exempts Metabase. Anthropic free tier or minimal spend. Fallback: hardcoded SQL queries. |
| 2 | **Metabase `/api/llm/generate-sql` not in Docker image** | Source exists but may require specific Metabase version | Verify with `metabase/metabase:latest`. If missing, try nightly or build from source. |
| 3 | **car_data volume (585K rows/session)** | Disk + time if naively ingested | Store only aggregated top_speeds (~22 rows). Server-side filter `speed>=250`. |
| 4 | **Docker on Windows** | Path issues, WSL2 memory, Docker not on PATH in Git Bash | Keep compose simple. Document PATH workaround from Learnimo. Test early. |
| 5 | **Metabase LLM generates wrong SQL** | Bad answers for NL queries | Log generated SQL in responses. Validate result has rows. Fallback to parameterized queries for demo. |

---

## 9. Open Questions

1. **Does `metabase/metabase:latest` Docker image include `/api/llm/generate-sql`?**
   - Quick check: start Metabase, hit the endpoint. If 404, try nightly or a specific version tag.

2. **Metabase dual-DB setup**: Can the same PostgreSQL serve as both app DB and data warehouse?
   - Almost certainly yes (different schemas), but verify during Milestone 1.

3. **LLM API key provider**: Anthropic is the default. Could also use OpenAI or OpenRouter per `llm/settings.clj`. Choose whichever key is available.

---

## Key Reference Files

| Purpose | Path |
|---------|------|
| Metabase OSS LLM API | `C:\repo\metabase\src\metabase\llm\api.clj` |
| Metabase LLM settings | `C:\repo\metabase\src\metabase\llm\settings.clj` |
| Open F1 car_data model | `C:\repo\openf1\src\openf1\services\ingestor_livetiming\core\processing\collections\car_data.py` |
| Open F1 laps model | `C:\repo\openf1\src\openf1\services\ingestor_livetiming\core\processing\collections\laps.py` |
| Open F1 query API | `C:\repo\openf1\src\openf1\services\query_api\app.py` |
| Learnimo Docker Compose | `C:\repo\engineering-daybook\docker-compose.yml` |

---

## Verification Plan

After each milestone:
- **M1:** `docker compose up` succeeds. `psql` shows f1_data schema. Metabase UI at localhost:3000 shows f1_data tables.
- **M2:** `curl POST /api/ingest` returns row counts. `psql SELECT count(*) FROM f1_data.laps` confirms data.
- **M3:** `curl POST /api/ask -d '{"question":"Who had the top speed at Suzuka 2026?"}'` returns a driver name + speed.
- **M4:** `curl POST /api/chart -d '{"prompt":"Top 10 lap times"}'` returns a URL. Opening that URL shows a Metabase chart.
- **M5:** Browser at localhost:5173 shows chat UI. Typing a question returns an answer. Typing a chart prompt shows an embedded chart.
