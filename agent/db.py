"""Read-only database access. The login itself (agent_ro) is read-only; this layer adds
bound parameters, a query timeout and a row cap."""
import urllib.parse
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event, text

from agent.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    engine = create_engine(
        "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(settings.db_connection_string),
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_query_timeout(dbapi_connection, _record):
        dbapi_connection.timeout = settings.query_timeout_s

    return engine


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def to_jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decimals and dates to strings, for state and LLM payloads."""
    return [{col: _jsonable(val) for col, val in row.items()} for row in rows]


def run_query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run one SELECT and return at most max_rows rows with native Python types
    (masking needs to tell text cells from numbers and dates)."""
    max_rows = get_settings().max_rows
    with get_engine().connect() as conn:
        result = conn.execute(text(sql), params)
        columns = list(result.keys())
        rows = result.fetchmany(max_rows)
        conn.rollback()
    return [dict(zip(columns, row)) for row in rows]
