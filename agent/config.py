"""Runtime settings, loaded once from the project's .env file."""
import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    db_connection_string: str
    openai_model: str
    max_rows: int = 200
    query_timeout_s: int = 5
    max_sql_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings(
            db_connection_string=os.environ["DB_CONNECTION_STRING"],
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )
    except KeyError as missing:
        raise RuntimeError(f"Missing {missing} in .env") from None


def default_as_of() -> date:
    """Today, unless AS_OF_DATE (YYYY-MM-DD) pins it, e.g. for repeatable demos."""
    pinned = os.environ.get("AS_OF_DATE")
    return date.fromisoformat(pinned) if pinned else date.today()
