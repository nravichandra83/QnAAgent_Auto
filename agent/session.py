"""The PII boundary around the graph.

A ContractSession is opened once per contract conversation:

    open:  resolve the sequence number -> create a vault -> load the customer's PII as known values
    ask:   mask question -> run graph (masked data only) -> unmask answer -> write audit record
    close: wipe the vault

    with ContractSession("CT-1001") as session:
        print(session.ask("How much is outstanding?").answer)
"""
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from agent import db
from agent.config import default_as_of
from agent.graph import build_graph
from agent.templates import CUSTOMER_PROFILE, RESOLVE_CONTRACT
from governance.audit import AuditLogger
from governance.masker import PiiMasker
from governance.policy import Policy, load_policy
from governance.vault import DEFAULT_VAULT_STORE, VaultStore

_PROFILE_TYPES = {
    "FirstName": "PERSON", "LastName": "PERSON", "AddressLine1": "ADDRESS", "AddressLine2": "ADDRESS",
    "Zip": "ZIP", "Phone": "PHONE", "Email": "EMAIL",
}


class ContractNotFound(LookupError):
    pass


@dataclass
class TurnResult:
    answer: str                         # unmasked, for the end user
    masked_question: str
    masked_answer: str
    state: dict[str, Any] = field(repr=False)   # final graph state (masked)


class ContractSession:
    def __init__(self, sequence_number: str, *, llm=None, app=None, policy: Policy | None = None,
                 vaults: VaultStore = DEFAULT_VAULT_STORE, audit: AuditLogger | None = None,
                 run_query: Callable[..., list[dict]] = db.run_query):
        self.sequence_number = sequence_number.strip()
        self._policy = policy or load_policy()
        self._masker = PiiMasker(self._policy)
        self._vaults = vaults
        self._audit = audit or AuditLogger(self._policy.audit_path)
        self._run_query = run_query
        self._app = app or build_graph(llm, policy=self._policy, masker=self._masker,
                                       vaults=vaults, run_query=run_query)

        found = run_query(RESOLVE_CONTRACT, {"seq": self.sequence_number})
        if not found:
            raise ContractNotFound(f"I couldn't find a contract with sequence number {self.sequence_number}.")
        self.contract_id: int = found[0]["Id"]
        self.contract_type: str = found[0]["ContractType"]

        self.session_id = uuid.uuid4().hex
        vault = vaults.create(self.session_id)
        for row in run_query(CUSTOMER_PROFILE, {"contract_id": self.contract_id}):
            for column, entity in _PROFILE_TYPES.items():
                vault.register_known(row.get(column), entity)
            if row.get("FirstName") and row.get("LastName"):
                vault.register_known(f"{row['FirstName']} {row['LastName']}", "PERSON")
        self._history: list[tuple[str, str]] = []
        self._turn = 0

    def ask(self, question: str, as_of: date | None = None) -> TurnResult:
        vault = self._vaults.get(self.session_id)
        self._turn += 1
        started = time.perf_counter()
        masked_q = self._masker.mask_text(question, vault)
        record: dict[str, Any] = {
            "session_id": self.session_id, "turn": self._turn, "sequence_number": self.sequence_number,
            "question": masked_q.text, "pii_input": dict(masked_q.counts),
        }
        try:
            state = self._app.invoke({
                "session_id": self.session_id,
                "sequence_number": self.sequence_number,
                "contract_id": self.contract_id,
                "contract_type": self.contract_type,
                "as_of_date": (as_of or default_as_of()).isoformat(),
                "question": masked_q.text,
                "history": list(self._history),
            })
        except Exception as err:
            record.update(outcome="error", error=type(err).__name__,
                          latency_ms=round((time.perf_counter() - started) * 1000))
            self._audit.write(record)
            raise

        answer = self._masker.unmask(state["answer"], vault)
        self._history.append((masked_q.text, state["answer"]))
        guard_total: Counter = Counter()
        for call in state.get("llm_calls", []):
            guard_total.update(call.get("guard_masked", {}))
        record.update(
            outcome="gave_up" if state.get("sql_errors") else "answered",
            intent=state.get("intent"),
            sql=state.get("sql"),
            sql_attempts=state.get("sql_attempts", 0),
            sql_errors=state.get("sql_errors", []),
            row_count=len(state.get("rows", [])),
            pii_columns=state.get("pii_columns"),
            pii_masked_output=state.get("pii_masked", {}),
            pii_guard_masked=dict(guard_total),
            llm_calls=state.get("llm_calls", []),
            answer=state["answer"],                       # masked
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        self._audit.write(record)
        return TurnResult(answer=answer, masked_question=masked_q.text, masked_answer=state["answer"],
                          state=state)

    def unmask_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Masked result rows -> rows for display to the end user (reveal policy applies)."""
        vault = self._vaults.get(self.session_id)
        return [{col: self._masker.unmask(val, vault) if isinstance(val, str) else val
                 for col, val in row.items()} for row in rows]

    def close(self) -> None:
        self._vaults.close(self.session_id)

    def __enter__(self) -> "ContractSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
