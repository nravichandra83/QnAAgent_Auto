"""Append-only JSON Lines audit log: one record per question.

Records hold masked text, SQL, counts and hashes only; never raw PII or the vault.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: dict[str, Any]) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **record}
        line = json.dumps(record, default=str, ensure_ascii=False)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
