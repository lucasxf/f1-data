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

# F1 points by finishing position (conventional races only)
POINTS_BY_POSITION: dict[int, int] = {
    1: 25, 2: 18, 3: 15, 4: 12, 5: 10,
    6: 8,  7: 6,  8: 4,  9: 2,  10: 1,
}
AVAILABLE_POINTS_PER_RACE = 101

# Override map for team colours if OpenF1 values conflict or need correction
TEAM_COLOUR_OVERRIDES: dict[str, str] = {
    # e.g. "Cadillac": "#1A1A1A"
}


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


def derive_race_results(positions: list[dict], drivers: list[dict]) -> list[dict]:
    """Compute final race results from OpenF1 position snapshots + driver info."""
    # Build driver lookup: driver_number -> {team_name, team_colour}
    driver_info: dict[int, dict] = {}
    for d in drivers:
        colour = d.get("team_colour") or ""
        hex_colour = f"#{colour}" if colour and not colour.startswith("#") else colour or None
        # Apply override if configured
        team = d.get("team_name") or ""
        if team in TEAM_COLOUR_OVERRIDES:
            hex_colour = TEAM_COLOUR_OVERRIDES[team]
        driver_info[d["driver_number"]] = {"team_name": team, "team_colour": hex_colour}

    # Final position = latest position snapshot per driver
    latest: dict[int, dict] = {}
    for entry in positions:
        drv = entry["driver_number"]
        if drv not in latest or entry["date"] > latest[drv]["date"]:
            latest[drv] = entry

    results = []
    for driver_number, pos_entry in latest.items():
        final_position = pos_entry["position"]
        points_earned = POINTS_BY_POSITION.get(final_position, 0)
        info = driver_info.get(driver_number, {})
        results.append({
            "driver_number": driver_number,
            "final_position": final_position,
            "points_earned": points_earned,
            "team_name": info.get("team_name"),
            "team_colour": info.get("team_colour"),
        })
    return results


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Apply DB schema migrations (idempotent)
    try:
        conn = db.get_conn()
        db.ensure_schema(conn)
        conn.close()
        log.info("Schema migrations applied.")
    except Exception as e:
        log.warning(f"Schema migration failed at startup: {e}")

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


class PointsChartRequest(BaseModel):
    year: int
    circuit: str | None = None
    session_type: str = "Race"


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

        positions = openf1.get_positions(session_key)
        results = derive_race_results(positions, drivers)
        result_count = db.upsert_race_results(conn, results, session_key)
        db.update_driver_colours(conn, drivers, session_key)

        return {
            "session_key": session_key,
            "rows": {
                "drivers": driver_count,
                "laps": lap_count,
                "top_speeds": speed_count,
                "race_results": result_count,
            },
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


@app.post("/api/points-chart")
def points_chart(req: PointsChartRequest):
    try:
        db_id, _ = _ensure_metabase_ready()
    except Exception as e:
        raise HTTPException(503, f"Metabase not ready: {e}")

    conn = db.get_conn()
    try:
        if req.circuit:
            # Single-race mode: look up session from DB
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_key FROM f1_data.sessions
                    WHERE circuit_short_name = %s AND year = %s AND session_name = %s
                    """,
                    (req.circuit, req.year, req.session_type),
                )
                row = cur.fetchone()
            if not row:
                raise HTTPException(
                    404,
                    f"No completed race found for {req.circuit} {req.year}. "
                    "Run /api/ingest first.",
                )
            session_key = row[0]
            breakdown = db.get_points_breakdown(conn, session_key)
            if not breakdown:
                raise HTTPException(
                    404,
                    f"No race results found for {req.circuit} {req.year}. "
                    "Re-ingest to populate race_results.",
                )
            sql = (
                f"SELECT team_name AS \"Team\", "
                f"SUM(points_earned) AS \"Points\", "
                f"ROUND(SUM(points_earned)::numeric / {AVAILABLE_POINTS_PER_RACE} * 100, 2) AS \"Efficiency %\" "
                f"FROM f1_data.race_results "
                f"WHERE session_key = {session_key} AND points_earned > 0 "
                f"GROUP BY team_name ORDER BY \"Points\" DESC"
            )
            title = f"Points Efficiency — {req.circuit} {req.year}"
        else:
            # Championship mode: all ingested races for the year
            breakdown = db.get_championship_breakdown(conn, req.year)
            if not breakdown:
                raise HTTPException(
                    404,
                    f"No race results found for {req.year}. "
                    "Ingest at least one race first.",
                )
            sql = (
                f"SELECT rr.team_name AS \"Team\", "
                f"SUM(rr.points_earned) AS \"Points\", "
                f"ROUND(SUM(rr.points_earned)::numeric / (COUNT(DISTINCT rr.session_key) * {AVAILABLE_POINTS_PER_RACE}) * 100, 2) AS \"Efficiency %\" "
                f"FROM f1_data.race_results rr "
                f"JOIN f1_data.sessions s ON s.session_key = rr.session_key "
                f"WHERE s.year = {req.year} AND rr.points_earned > 0 "
                f"GROUP BY rr.team_name ORDER BY \"Points\" DESC"
            )
            title = f"Championship Points Efficiency — {req.year}"
    finally:
        conn.close()

    pie_colors = {
        row["team_name"]: row["team_colour"]
        for row in breakdown
        if row.get("team_colour")
    }
    viz_settings = {
        "pie.colors": pie_colors,
        "pie.percent_visibility": "inside",
        "pie.show_legend": True,
    }

    log.info(f"Points chart SQL: {sql}")
    card = mb.create_card(db_id, sql, name=title, display="pie", visualization_settings=viz_settings)
    embed_url = mb.make_card_public(card["id"])

    return {
        "embed_url": embed_url,
        "sql": sql,
        "breakdown": [
            {
                "team_name": r["team_name"],
                "team_colour": r.get("team_colour"),
                "team_points": int(r["team_points"]),
                "efficiency_pct": float(r["efficiency_pct"]),
            }
            for r in breakdown
        ],
    }
