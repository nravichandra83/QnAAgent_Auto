"""Graph state. Every text field here is MASKED: raw PII never enters the graph.

The session layer (agent/session.py) masks the question before the graph runs and unmasks
the answer after it. The vault itself lives outside the state (governance/vault.py) and is
looked up by session_id, so state snapshots, traces or checkpoints cannot leak it.
"""
import operator
from typing import Annotated, Any, Literal, TypedDict

Intent = Literal["status", "next_due_date", "invoice_amount", "outstanding_amount", "adhoc"]
CORE_INTENTS: tuple[str, ...] = ("status", "next_due_date", "invoice_amount", "outstanding_amount")


class AgentState(TypedDict, total=False):
    # Session and contract scope (set by the session layer)
    session_id: str
    sequence_number: str
    contract_id: int
    contract_type: str
    as_of_date: str                          # YYYY-MM-DD

    # Masked conversation
    question: str
    history: list[tuple[str, str]]           # prior (question, answer) pairs, masked

    # Routing and SQL
    intent: Intent
    sql: str
    sql_errors: list[str]                    # validator or database errors for the current SQL
    sql_attempts: int

    # Results (masked at fetch time)
    rows: list[dict[str, Any]]
    pii_columns: dict[str, str] | None       # output column -> entity type; None if lineage failed
    pii_masked: dict[str, int]               # entity type -> values masked in rows
    answer: str                              # masked; the session unmasks it for the user

    # Governance: one record per LLM call, appended by each LLM node
    llm_calls: Annotated[list[dict[str, Any]], operator.add]
