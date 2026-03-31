-- Migration 001: Add race_results table and team_colour column to drivers
-- Safe to run multiple times (idempotent).

ALTER TABLE f1_data.drivers ADD COLUMN IF NOT EXISTS team_colour VARCHAR(7);

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
