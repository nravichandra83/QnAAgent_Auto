"""The PII vault: a per-session, in-memory map between real values and tokens like <PERSON_1>.

The vault never enters graph state, logs, audit records or LLM payloads; the graph only
carries a session_id. A production deployment would back VaultStore with an encrypted,
TTL-bound store (e.g. Redis) behind the same interface.
"""
import re
import threading
import time
from collections import Counter

TOKEN_RE = re.compile(r"<([A-Z_]+?)_(\d+)>")


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


class Vault:
    def __init__(self) -> None:
        self._token_to_value: dict[str, str] = {}
        self._value_to_token: dict[tuple[str, str], str] = {}
        self._counters: Counter[str] = Counter()
        self._known: dict[str, tuple[str, str]] = {}      # normalized -> (original, entity type)

    def tokenize(self, value: str, entity_type: str) -> str:
        """Stable token for a value: the same value always gets the same token in a session,
        so the LLM can still reason about equality ("is <EMAIL_1> the email on file?")."""
        key = (entity_type, _normalize(value))
        token = self._value_to_token.get(key)
        if token is None:
            self._counters[entity_type] += 1
            token = f"<{entity_type}_{self._counters[entity_type]}>"
            self._value_to_token[key] = token
            self._token_to_value[token] = " ".join(value.split())
        return token

    def register_known(self, value: str | None, entity_type: str) -> None:
        """Remember a value that must be masked wherever it appears in free text."""
        if value and value.strip():
            self._known.setdefault(_normalize(value), (" ".join(value.split()), entity_type))

    def known_values(self) -> list[tuple[str, str]]:
        """(value, entity type), longest first so 'John Carter' wins over 'John'."""
        return sorted(self._known.values(), key=lambda item: len(item[0]), reverse=True)

    def value_of(self, token: str) -> str | None:
        return self._token_to_value.get(token)

    def __len__(self) -> int:
        return len(self._token_to_value)

    def __repr__(self) -> str:                             # never print values
        return f"Vault(<{len(self._token_to_value)} tokens, {len(self._known)} known values: redacted>)"

    def clear(self) -> None:
        self._token_to_value.clear()
        self._value_to_token.clear()
        self._known.clear()
        self._counters.clear()


class VaultStore:
    """Session-scoped vaults with an idle TTL. Thread-safe."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._vaults: dict[str, tuple[Vault, float]] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str) -> Vault:
        with self._lock:
            self._purge_expired()
            vault = Vault()
            self._vaults[session_id] = (vault, time.monotonic())
            return vault

    def get(self, session_id: str) -> Vault:
        """Fails closed: an unknown or expired session raises KeyError."""
        with self._lock:
            self._purge_expired()
            vault, _ = self._vaults[session_id]
            self._vaults[session_id] = (vault, time.monotonic())
            return vault

    def close(self, session_id: str) -> None:
        with self._lock:
            entry = self._vaults.pop(session_id, None)
        if entry:
            entry[0].clear()

    def _purge_expired(self) -> None:
        now = time.monotonic()
        for session_id in [s for s, (_, seen) in self._vaults.items() if now - seen > self._ttl]:
            self._vaults.pop(session_id)[0].clear()


DEFAULT_VAULT_STORE = VaultStore()
