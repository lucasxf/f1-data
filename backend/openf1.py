"""Open F1 API client."""

import requests

BASE_URL = "https://api.openf1.org/v1"


def _get(path: str, raw: str = "", **params) -> list[dict]:
    """Fetch from Open F1 API. `raw` is appended verbatim to the query string (for comparison operators)."""
    url = f"{BASE_URL}/{path}"
    resp = requests.get(url, params=params, timeout=30)
    # Append raw filter (e.g. "speed>=250") without URL-encoding
    if raw:
        sep = "&" if resp.request.url and "?" in resp.request.url else "?"
        resp = requests.get(resp.request.url + sep + raw, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_session(circuit_short_name: str, year: int, session_name: str = "Race") -> dict | None:
    results = _get("sessions", circuit_short_name=circuit_short_name, year=year, session_name=session_name)
    return results[0] if results else None


def get_drivers(session_key: int) -> list[dict]:
    return _get("drivers", session_key=session_key)


def get_laps(session_key: int) -> list[dict]:
    return _get("laps", session_key=session_key)


def get_top_speed_telemetry(session_key: int, speed_threshold: int = 250) -> list[dict]:
    """Fetch only high-speed telemetry to avoid downloading 585K rows."""
    return _get("car_data", session_key=session_key, raw=f"speed>={speed_threshold}")


def get_positions(session_key: int) -> list[dict]:
    """Fetch all position snapshots for a session. Final position = latest entry per driver."""
    return _get("position", session_key=session_key)
