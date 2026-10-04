import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.nodes import IntentDecision, SqlDraft  # noqa: E402
from governance.audit import AuditLogger  # noqa: E402

# SSNs are unreadable to agent_ro, so the seeded values are listed here (db/seed.sql)
SEEDED_SSNS = ["900-12-3456", "900-23-4567", "900-34-5678", "900-45-6789", "900-56-7890",
               "900-67-8901", "900-78-9012", "900-89-0123", "900-90-1234"]


@pytest.fixture(scope="session")
def db_available():
    from agent.db import run_query
    try:
        run_query("SELECT 1 AS ok", {})
    except Exception as err:  # pragma: no cover - environment dependent
        pytest.skip(f"SQL Server not reachable: {err}")


@pytest.fixture(scope="session")
def seeded_pii(db_available) -> list[str]:
    """Every PII value of every customer in the test data (min length 3)."""
    from agent.db import run_query
    rows = run_query("SELECT FirstName, LastName, AddressLine1, AddressLine2, Zip, Phone, Email "
                     "FROM dbo.Customers", {})
    values = {str(v) for row in rows for v in row.values() if v and len(str(v)) >= 3}
    values |= {f"{r['FirstName']} {r['LastName']}" for r in rows}
    return sorted(values | set(SEEDED_SSNS), key=len, reverse=True)


class FakeLLM:
    """Stands in for the chat model: fixed intent, queued SQL drafts, fixed (or computed) answer.
    Records every payload so tests can inspect exactly what would be sent to the LLM."""

    def __init__(self, intent="status", sql_drafts=(), answer="ok"):
        self.intent = intent
        self.sql_drafts = list(sql_drafts)
        self.answer = answer
        self.calls: list[tuple[str, list]] = []

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, messages):
                outer.calls.append((schema.__name__, messages))
                if schema is IntentDecision:
                    return IntentDecision(intent=outer.intent)
                return SqlDraft(sql=outer.sql_drafts.pop(0))

        return _Structured()

    def invoke(self, messages):
        self.calls.append(("compose", messages))
        answer = self.answer(messages) if callable(self.answer) else self.answer
        return AIMessage(answer)

    def sent_text(self) -> str:
        """Everything this fake 'sent to the LLM', as one string."""
        return "\n".join(str(m.content) for _, messages in self.calls for m in messages)


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture
def audit_log(tmp_path) -> AuditLogger:
    return AuditLogger(tmp_path / "audit.jsonl")


@pytest.fixture
def make_session(db_available, audit_log):
    from agent.session import ContractSession
    opened = []

    def _make(seq: str, llm, **kwargs):
        session = ContractSession(seq, llm=llm, audit=audit_log, **kwargs)
        opened.append(session)
        return session

    yield _make
    for session in opened:
        session.close()
