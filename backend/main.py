"""F1 x Metabase Analytics -- FastAPI backend."""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db
import openf1
import metabase_client as mb

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Cached at startup
_db_id: int | None = None
_table_ids: dict[str, int] = {}


def _ensure_metabase_ready():
    """Ensure Metabase has the f1_data warehouse registered and return (db_id, table_ids)."""
    global _db_id, _table_ids

    if _db_id and _table_ids:
        return _db_id, _table_ids

    # Find or register the f1_data warehouse in Metabase
    _db_id = mb.get_f1_database_id()
    if not _db_id:
        log.info("Registering f1_data warehouse in Metabase...")
        result = mb.add_database(
            name="F1 Data",
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )
        _db_id = result["id"]
        log.info(f"Registered Metabase database id={_db_id}")

    _table_ids = mb.get_table_ids(_db_id)
    log.info(f"Metabase table IDs: {_table_ids}")
    return _db_id, _table_ids


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Try to connect to Metabase at startup (best-effort; Metabase may still be booting)
    try:
        _ensure_metabase_ready()
    except Exception as e:
        log.warning(f"Metabase not ready at startup (will retry on first request): {e}")
    yield


app = FastAPI(title="F1 Analytics API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response models ---

class IngestRequest(BaseModel):
    circuit: str
    year: int
    session_type: str = "Race"


class AskRequest(BaseModel):
    question: str


class ChartRequest(BaseModel):
    prompt: str


# --- Helpers ---

def _ingest_session(circuit: str, year: int, session_name: str) -> dict:
    session = openf1.get_session(circuit, year, session_name)
    if not session:
        raise HTTPException(404, f"No session found: {circuit} {year} {session_name}")

    session_key = session["session_key"]
    conn = db.get_conn()
    try:
        if db.session_exists(conn, session_key):
            return {"session_key": session_key, "rows": "already ingested"}

        db.upsert_session(conn, session)

        drivers = openf1.get_drivers(session_key)
        driver_count = db.upsert_drivers(conn, drivers, session_key)

        laps = openf1.get_laps(session_key)
        lap_count = db.upsert_laps(conn, laps, session_key)

        telemetry = openf1.get_top_speed_telemetry(session_key)
        speed_count = db.upsert_top_speeds(conn, telemetry, session_key)

        return {
            "session_key": session_key,
            "rows": {"drivers": driver_count, "laps": lap_count, "top_speeds": speed_count},
        }
    finally:
        conn.close()


# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/sessions")
def list_sessions():
    conn = db.get_conn()
    try:
        return db.list_sessions(conn)
    finally:
        conn.close()


@app.post("/api/ingest")
def ingest(req: IngestRequest):
    return _ingest_session(req.circuit, req.year, req.session_type)


@app.post("/api/ask")
def ask(req: AskRequest):
    try:
        db_id, table_ids = _ensure_metabase_ready()
    except Exception as e:
        raise HTTPException(503, f"Metabase not ready: {e}")

    if not table_ids:
        raise HTTPException(503, "No f1_data tables found in Metabase — run /api/ingest first")

    try:
        sql = mb.generate_sql(req.question, db_id, list(table_ids.values()))
        log.info(f"Generated SQL: {sql}")
    except Exception as e:
        raise HTTPException(502, f"SQL generation failed: {e}")

    try:
        rows = mb.run_native_query(db_id, sql)
    except Exception as e:
        raise HTTPException(502, f"Query execution failed: {e}")

    return {"answer": rows, "sql": sql}


@app.post("/api/chart")
def chart(req: ChartRequest):
    try:
        db_id, table_ids = _ensure_metabase_ready()
    except Exception as e:
        raise HTTPException(503, f"Metabase not ready: {e}")

    if not table_ids:
        raise HTTPException(503, "No f1_data tables found in Metabase — run /api/ingest first")

    try:
        sql = mb.generate_sql(req.prompt, db_id, list(table_ids.values()))
        log.info(f"Generated SQL: {sql}")
    except Exception as e:
        raise HTTPException(502, f"SQL generation failed: {e}")

    card = mb.create_card(db_id, sql, name=req.prompt[:100], display="table")
    embed_url = mb.make_card_public(card["id"])

    return {"embed_url": embed_url, "sql": sql}
