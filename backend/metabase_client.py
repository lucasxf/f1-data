"""Metabase REST API client."""

import os
import requests

_session_token: str | None = None
_mb_url = os.environ.get("METABASE_URL", "http://localhost:3000")


def _headers() -> dict:
    return {"X-Metabase-Session": _get_token(), "Content-Type": "application/json"}


def _get_token() -> str:
    global _session_token
    if _session_token:
        return _session_token
    resp = requests.post(
        f"{_mb_url}/api/session",
        json={
            "username": os.environ["MB_ADMIN_EMAIL"],
            "password": os.environ["MB_ADMIN_PASSWORD"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    _session_token = resp.json()["id"]
    return _session_token


def reset_token():
    global _session_token
    _session_token = None


def get_databases() -> list[dict]:
    resp = requests.get(f"{_mb_url}/api/database", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json().get("data", [])


def get_f1_database_id() -> int | None:
    """Find the Metabase database ID for the f1_data warehouse."""
    for db in get_databases():
        details = db.get("details", {})
        if details.get("db") == os.environ.get("DB_NAME", "f1") or db.get("name", "").lower().startswith("f1"):
            return db["id"]
    return None


def get_table_ids(database_id: int) -> dict[str, int]:
    """Return a mapping of table name -> Metabase table ID for the f1_data schema."""
    resp = requests.get(f"{_mb_url}/api/database/{database_id}/metadata", headers=_headers(), timeout=10)
    resp.raise_for_status()
    tables = resp.json().get("tables", [])
    return {t["name"]: t["id"] for t in tables if t.get("schema") == "f1_data"}


def generate_sql(prompt: str, database_id: int, table_ids: list[int]) -> str:
    """Call Metabase's OSS BYOK SQL generation endpoint."""
    resp = requests.post(
        f"{_mb_url}/api/llm/generate-sql",
        headers=_headers(),
        json={
            "prompt": prompt,
            "database_id": database_id,
            "referenced_entities": [{"model": "table", "id": tid} for tid in table_ids],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["sql"]


def run_native_query(database_id: int, sql: str) -> list[dict]:
    """Execute a native SQL query via /api/dataset and return rows as dicts."""
    resp = requests.post(
        f"{_mb_url}/api/dataset",
        headers=_headers(),
        json={
            "database": database_id,
            "type": "native",
            "native": {"query": sql},
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    cols = [c["name"] for c in data["data"]["cols"]]
    return [dict(zip(cols, row)) for row in data["data"]["rows"]]


def create_card(database_id: int, sql: str, name: str, display: str = "table") -> dict:
    """Create a saved question (card) in Metabase."""
    resp = requests.post(
        f"{_mb_url}/api/card",
        headers=_headers(),
        json={
            "name": name,
            "display": display,
            "dataset_query": {
                "database": database_id,
                "type": "native",
                "native": {"query": sql},
            },
            "visualization_settings": {},
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def make_card_public(card_id: int) -> str:
    """Enable public sharing on a card and return the public UUID."""
    resp = requests.post(
        f"{_mb_url}/api/card/{card_id}/public_link",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    uuid = resp.json()["uuid"]
    # Use the browser-accessible URL (localhost), not the Docker-internal hostname
    public_base = os.environ.get("METABASE_PUBLIC_URL", "http://localhost:3000")
    return f"{public_base}/public/question/{uuid}"


def add_database(name: str, host: str, port: int, dbname: str, user: str, password: str) -> dict:
    """Register the f1 PostgreSQL as a Metabase data source."""
    resp = requests.post(
        f"{_mb_url}/api/database",
        headers=_headers(),
        json={
            "name": name,
            "engine": "postgres",
            "details": {
                "host": host,
                "port": port,
                "dbname": dbname,
                "user": user,
                "password": password,
                "schema-filters-type": "inclusion",
                "schema-filters-patterns": "f1_data",
            },
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
