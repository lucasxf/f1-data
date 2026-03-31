# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project overview

MVP analytics project combining **Formula 1 telemetry** (Open F1 API) with **Metabase OSS** analytics. Built as a portfolio project for a Metabase backend engineering interview.

**Current state:** MVP is working end-to-end. All 5 implementation milestones are complete. See `docs/architecture-plan.md` for the full architecture rationale.

**Two use cases:**
1. NL query → "Top speed at Suzuka 2026?" → text answer with driver + speed
2. Prompt-to-chart → "Top 10 lap times" → embedded Metabase chart in React UI

---

## Tech stack

| Component | Technology |
|---|---|
| Database | PostgreSQL 15 (`pgvector/pgvector:pg15`) |
| Analytics | Metabase OSS (`metabase/metabase:latest`) |
| Backend | Python 3.12, FastAPI 0.115, psycopg2, requests |
| Frontend | React 18, TypeScript, Vite 6 |
| Infrastructure | Docker Compose (3 services) |
| LLM | Anthropic (via Metabase's BYOK endpoint) |

---

## Architecture

**Docker services (3):** `f1-postgres:5432`, `f1-metabase:3000`, `f1-backend:8080`
**Local process:** React/Vite dev server on port 5173

**Internal vs external URLs — important distinction:**
- Backend calls Metabase at `http://metabase:3000` (Docker internal hostname)
- Public embed URLs returned to the browser use `http://localhost:3000`
- This is configured via `METABASE_URL` vs `METABASE_PUBLIC_URL` env vars in docker-compose.yml

**PostgreSQL dual-duty:** The same PostgreSQL instance serves as both Metabase's application database (configured via `MB_DB_*` env vars) and the F1 data warehouse (the `f1_data` schema). This is intentional — one service instead of two.

---

## Key conventions

### Backend (`backend/`)

- **FastAPI sync endpoints** — not async (except the lifespan handler). Use sync `def`, not `async def`.
- **DB connections** — create and close per-request in `db.py` via `db.get_conn()`. Not pooled.
- **Metabase session token** — cached in a module-level global `_session_token` in `metabase_client.py`. Cleared via `reset_token()` if a 401 is received.
- **Metabase table IDs** — cached in `_table_ids` dict in `main.py`. Populated at startup (best-effort) and on first request if startup failed.

### Frontend (`frontend/`)

- **Single-file app** — all logic in `frontend/src/App.tsx`. No routing, no state manager.
- **Inline styles** — no CSS files, no Tailwind. Style objects at the bottom of App.tsx.
- **API calls** — use the empty string base URL `''`; Vite proxies `/api` to `localhost:8080`.

### Docker

- **Code changes require a rebuild:** `docker compose build backend && docker compose up -d backend`
- **`docker compose restart backend` does NOT pick up code changes** — it restarts the existing container without rebuilding the image.
- **Schema initialization** — `infra/init.sql` is mounted into PostgreSQL's `docker-entrypoint-initdb.d/`. It only runs on the first boot (when the volume is empty). To re-run it, destroy the volume: `docker compose down -v`.

---

## Development workflow

```bash
# Start all Docker services
docker compose up -d

# Rebuild and restart backend after code changes
docker compose build backend && docker compose up -d backend

# Start frontend
cd frontend && npm run dev

# Check backend logs
docker logs f1-backend --tail 30

# Ingest Suzuka 2026 Race (the demo dataset)
curl -X POST http://localhost:8080/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"circuit": "Suzuka", "year": 2026, "session_type": "Race"}'

# Test NL query
curl -X POST http://localhost:8080/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Who had the top speed at Suzuka in 2026?"}'

# Test chart generation
curl -X POST http://localhost:8080/api/chart \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Top 10 lap times at Suzuka 2026, fastest first"}'

# Inspect database
docker exec f1-postgres psql -U f1 -d f1 -c \
  "SELECT count(*) FROM f1_data.laps;"
```

---

## Open F1 API notes

- **Base URL:** `https://api.openf1.org/v1`
- **Rate limit:** 30 requests per 10 seconds per IP
- **No pagination** — all matching results are returned in one response
- **Filtering:** standard params work fine (`?session_key=11253`), but **comparison operators (`>=`, `<=`) must NOT be URL-encoded**. The `requests` library encodes `>=` as `%3E%3D`, which the API rejects with 404. Workaround: the `_get()` function in `openf1.py` accepts a `raw` parameter that is appended verbatim to the URL after requests builds it.
- **car_data volume:** At ~3.7 Hz with 22 drivers, a full race session is ~585K rows. We do NOT store raw car_data. Instead, we fetch `car_data?session_key=X&speed>=250` (server-side filter) and aggregate to max speed per driver — resulting in ~22 rows stored in `top_speeds`.
- **circuit_short_name examples:** `"Suzuka"`, `"Melbourne"`, `"Shanghai"`, `"Monza"`, `"Spa-Francorchamps"`, `"Monte Carlo"`

---

## Metabase API notes

**Authentication:** `POST /api/session` with `{username, password}` → returns `{id: token}`. Use `X-Metabase-Session: <token>` header on all subsequent requests.

**OSS BYOK SQL generation:** `POST /api/llm/generate-sql`
- Requires `MB_LLM_ANTHROPIC_API_KEY` set in Metabase's environment
- Request body: `{"prompt": str, "database_id": int, "referenced_entities": [{"model": "table", "id": int}, ...]}`
- **`model` not `type`** — the field is `model: "table"`, NOT `type: "table"`. Using `type` returns a 400.
- Returns `{"sql": str, "referenced_entities": [...]}`

**Ad-hoc query execution:** `POST /api/dataset`
- Body: `{"database": db_id, "type": "native", "native": {"query": sql}}`
- Returns rows in `data.rows` with column names in `data.cols[].name`

**Creating a saved question (card):** `POST /api/card`
- Body includes `dataset_query`, `display` (e.g. `"table"`, `"bar"`), `visualization_settings`

**Enabling public embed:** `POST /api/card/{id}/public_link` → returns `{"uuid": str}`
- Public URL pattern: `{METABASE_PUBLIC_URL}/public/question/{uuid}`
- Public sharing is enabled by default in Metabase OSS

**Discovering table IDs:** `GET /api/database/{id}/metadata` → `tables[].id` and `tables[].schema`
- Filter by `schema == "f1_data"` to get the right tables

---

## Database

**Schema:** `f1_data` (in the `f1` database)

| Table | Key columns | Notes |
|---|---|---|
| `sessions` | `session_key` (PK), `circuit_short_name`, `year`, `session_name` | Source of truth for what's ingested |
| `drivers` | FK to sessions, `driver_number`, `full_name`, `team_name` | One row per driver per session |
| `laps` | FK to sessions, `driver_number`, `lap_number`, `lap_duration` | ~1,100 rows per race |
| `top_speeds` | FK to sessions, `driver_number`, `max_speed` | Pre-aggregated; ~22 rows per race |

All inserts use `ON CONFLICT DO NOTHING` (or `DO UPDATE` for top_speeds) — safe to re-run.

---

## Known issues / gotchas

1. **`session_exists` is checked before full ingestion completes.** If an ingestion fails mid-way (e.g. after inserting `sessions` and `drivers` but before `top_speeds`), subsequent calls to `/api/ingest` will return `"already ingested"` even though `top_speeds` is empty. Fix: manually delete the session row and re-ingest. `DELETE FROM f1_data.sessions WHERE session_key=X` cascades to nothing (children have FKs but no cascade delete defined), so delete children first: `top_speeds → laps → drivers → sessions`.

2. **Open F1 comparison filter URL encoding.** The `requests` library URL-encodes `>=` symbols. Always use the `raw` parameter in `openf1._get()` for comparison filters, never pass them as `**params`.

3. **Docker rebuild vs restart.** `docker compose restart` does NOT rebuild. After any Python file change: `docker compose build backend && docker compose up -d backend`.

4. **Metabase credentials mismatch.** If `MB_ADMIN_EMAIL`/`MB_ADMIN_PASSWORD` in `.env` don't match what was entered in the Metabase first-run setup wizard, the backend's `POST /api/session` will fail. Update `.env` to match what was used during setup — Metabase stores its own credentials, they can't be overridden by env vars after initial setup.

5. **Metabase startup time.** Metabase takes ~60 seconds to fully initialize on first boot. The backend handles this gracefully (best-effort startup connection, retries on first request), but the Metabase UI at `localhost:3000` will show a loading screen during this period.

---

## Git workflow

- **Branch structure:** `main` ← `develop` ← `feat/*`
- **Never push directly to `main`.** All code reaches main via PRs through develop.
- **Conventional commits:** `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`
- **`gh` CLI** is on PATH (configured in `.claude/settings.json`). Use it for PRs.
