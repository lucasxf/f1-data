"""PostgreSQL connection and data insertion helpers."""

import os
import psycopg2
from psycopg2.extras import execute_values


def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def session_exists(conn, session_key: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM f1_data.sessions WHERE session_key = %s", (session_key,))
        return cur.fetchone() is not None


def upsert_session(conn, session: dict):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO f1_data.sessions (session_key, meeting_key, circuit_short_name, country_name, year, session_name, date_start)
            VALUES (%(session_key)s, %(meeting_key)s, %(circuit_short_name)s, %(country_name)s, %(year)s, %(session_name)s, %(date_start)s)
            ON CONFLICT (session_key) DO NOTHING
            """,
            session,
        )
    conn.commit()


def upsert_drivers(conn, drivers: list[dict], session_key: int):
    rows = [
        (session_key, d["driver_number"], d.get("full_name"), d.get("name_acronym"), d.get("team_name"))
        for d in drivers
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO f1_data.drivers (session_key, driver_number, full_name, name_acronym, team_name)
            VALUES %s
            ON CONFLICT (session_key, driver_number) DO NOTHING
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def upsert_laps(conn, laps: list[dict], session_key: int):
    rows = [
        (
            session_key,
            lap["driver_number"],
            lap["lap_number"],
            lap.get("lap_duration"),
            lap.get("duration_sector_1"),
            lap.get("duration_sector_2"),
            lap.get("duration_sector_3"),
            lap.get("i1_speed"),
            lap.get("i2_speed"),
            lap.get("st_speed"),
            lap.get("is_pit_out_lap", False),
        )
        for lap in laps
        if lap.get("lap_duration") is not None  # skip incomplete laps
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO f1_data.laps
              (session_key, driver_number, lap_number, lap_duration,
               duration_sector_1, duration_sector_2, duration_sector_3,
               i1_speed, i2_speed, st_speed, is_pit_out_lap)
            VALUES %s
            ON CONFLICT (session_key, driver_number, lap_number) DO NOTHING
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def upsert_top_speeds(conn, telemetry: list[dict], session_key: int):
    """Aggregate raw telemetry to max speed per driver and upsert."""
    from collections import defaultdict

    max_by_driver: dict[int, dict] = defaultdict(lambda: {"speed": 0, "date": None})
    for row in telemetry:
        drv = row["driver_number"]
        spd = row.get("speed") or 0
        if spd > max_by_driver[drv]["speed"]:
            max_by_driver[drv]["speed"] = spd
            max_by_driver[drv]["date"] = row.get("date")

    rows = [
        (session_key, drv, data["speed"], data["date"])
        for drv, data in max_by_driver.items()
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO f1_data.top_speeds (session_key, driver_number, max_speed, recorded_at)
            VALUES %s
            ON CONFLICT (session_key, driver_number)
            DO UPDATE SET max_speed = EXCLUDED.max_speed, recorded_at = EXCLUDED.recorded_at
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def list_sessions(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT session_key, circuit_short_name, country_name, year, session_name, date_start
            FROM f1_data.sessions
            ORDER BY date_start DESC
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
