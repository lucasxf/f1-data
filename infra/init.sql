-- F1 Data Schema
-- Runs once on first PostgreSQL container start

CREATE SCHEMA IF NOT EXISTS f1_data;

CREATE TABLE IF NOT EXISTS f1_data.sessions (
    session_key    INTEGER PRIMARY KEY,
    meeting_key    INTEGER NOT NULL,
    circuit_short_name VARCHAR(50),
    country_name   VARCHAR(100),
    year           INTEGER,
    session_name   VARCHAR(50),
    date_start     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS f1_data.drivers (
    id             SERIAL PRIMARY KEY,
    session_key    INTEGER NOT NULL REFERENCES f1_data.sessions(session_key),
    driver_number  INTEGER NOT NULL,
    full_name      VARCHAR(200),
    name_acronym   VARCHAR(5),
    team_name      VARCHAR(100),
    team_colour    VARCHAR(7),
    UNIQUE(session_key, driver_number)
);

CREATE TABLE IF NOT EXISTS f1_data.laps (
    id               SERIAL PRIMARY KEY,
    session_key      INTEGER NOT NULL REFERENCES f1_data.sessions(session_key),
    driver_number    INTEGER NOT NULL,
    lap_number       INTEGER NOT NULL,
    lap_duration     FLOAT,
    duration_sector_1 FLOAT,
    duration_sector_2 FLOAT,
    duration_sector_3 FLOAT,
    i1_speed         INTEGER,
    i2_speed         INTEGER,
    st_speed         INTEGER,
    is_pit_out_lap   BOOLEAN DEFAULT FALSE,
    UNIQUE(session_key, driver_number, lap_number)
);

-- Pre-aggregated: max speed per driver per session (avoids storing 585K raw telemetry rows)
CREATE TABLE IF NOT EXISTS f1_data.top_speeds (
    id             SERIAL PRIMARY KEY,
    session_key    INTEGER NOT NULL REFERENCES f1_data.sessions(session_key),
    driver_number  INTEGER NOT NULL,
    max_speed      INTEGER,
    recorded_at    TIMESTAMP,
    UNIQUE(session_key, driver_number)
);

-- Race results: final position + points earned per driver per session
CREATE TABLE IF NOT EXISTS f1_data.race_results (
    id             SERIAL PRIMARY KEY,
    session_key    INTEGER NOT NULL REFERENCES f1_data.sessions(session_key),
    driver_number  INTEGER NOT NULL,
    final_position INTEGER NOT NULL,
    points_earned  INTEGER NOT NULL DEFAULT 0,
    team_name      VARCHAR(100),
    team_colour    VARCHAR(7),
    UNIQUE(session_key, driver_number)
);
