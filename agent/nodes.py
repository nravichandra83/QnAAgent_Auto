"""Graph nodes (spec: Agent architecture). Only classify_intent, generate_sql and
compose_answer call the LLM, and every call goes through the egress guard."""
import hashlib
import json
from datetime import date
from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from agent import db
from agent.prompts import CLASSIFY_SYSTEM, COMPOSE_SYSTEM, GENERATE_SQL_SYSTEM
from agent.state import AgentState, Intent
from agent.templates import CORE_TEMPLATES
from agent.validator import used_params, validate_sql
from governance.guard import EgressGuard
from governance.lineage import classify_output_columns
from governance.masker import PiiMasker
from governance.policy import Policy
from governance.vault import VaultStore

GIVE_UP_MESSAGE = "I couldn't build a safe query for that question. Please try rephrasing it."


class IntentDecision(BaseModel):
    intent: Intent = Field(description="The single best-matching intent")


class SqlDraft(BaseModel):
    sql: str = Field(description="One T-SQL SELECT statement using :contract_id and optionally :as_of_date")


def _history_messages(state: AgentState) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for question, answer in state.get("history", [])[-3:]:
        messages += [HumanMessage(question), AIMessage(answer)]
    return messages


def _bind_params(state: AgentState, sql: str) -> dict[str, Any]:
    available = {"contract_id": state["contract_id"], "as_of_date": date.fromisoformat(state["as_of_date"])}
    names = used_params(sql)
    return {k: v for k, v in available.items() if k in names}


class AgentNodes:
    def __init__(self, llm: BaseChatModel, policy: Policy, masker: PiiMasker, vaults: VaultStore,
                 run_query: Callable[..., list[dict]] = db.run_query):
        self._llm = llm
        self._classifier = llm.with_structured_output(IntentDecision)
        self._sql_writer = llm.with_structured_output(SqlDraft)
        self._policy = policy
        self._masker = masker
        self._guard = EgressGuard(masker, policy.guard_mode)
        self._vaults = vaults
        self._run_query = run_query

    def _call_llm(self, node: str, runnable, messages: list[BaseMessage], state: AgentState):
        """Every LLM call: egress guard first, then a metadata record for the audit log."""
        messages, findings = self._guard.check(messages, self._vaults.get(state["session_id"]))
        payload = "\n".join(str(m.content) for m in messages)
        record: dict[str, Any] = {
            "node": node,
            "chars": len(payload),
            "sha256": hashlib.sha256(payload.encode()).hexdigest()[:16],
            "guard_masked": dict(findings),
        }
        if self._policy.audit_include_payloads:
            record["payload"] = payload          # masked text only
        return runnable.invoke(messages), record

    # --- routing --------------------------------------------------------------------
    def classify_intent(self, state: AgentState) -> dict:
        messages = [SystemMessage(CLASSIFY_SYSTEM), *_history_messages(state), HumanMessage(state["question"])]
        decision, record = self._call_llm("classify_intent", self._classifier, messages, state)
        return {"intent": decision.intent, "llm_calls": [record]}

    # --- SQL ------------------------------------------------------------------------
    def run_template(self, state: AgentState) -> dict:
        return {"sql": CORE_TEMPLATES[state["intent"]].strip(), "sql_errors": []}

    def generate_sql(self, state: AgentState) -> dict:
        attempts = state.get("sql_attempts", 0) + 1
        context = (f"Current contract: {state['sequence_number']} "
                   f"(ContractType = {state['contract_type']}). As-of date is bound to :as_of_date.")
        messages = [SystemMessage(GENERATE_SQL_SYSTEM), SystemMessage(context), *_history_messages(state),
                    HumanMessage(state["question"])]
        if state.get("sql_errors"):
            messages.append(HumanMessage(
                "Your previous query was rejected:\n" + state.get("sql", "") +
                "\nProblems:\n- " + "\n- ".join(state["sql_errors"]) +
                "\nWrite a corrected query."))
        draft, record = self._call_llm("generate_sql", self._sql_writer, messages, state)
        # Read the previous errors above; clear them now because they belong to the old SQL
        return {"sql": draft.sql.strip().rstrip(";"), "sql_attempts": attempts, "sql_errors": [],
                "llm_calls": [record]}

    def validate_sql(self, state: AgentState) -> dict:
        return {"sql_errors": validate_sql(state["sql"])}

    def execute_sql(self, state: AgentState) -> dict:
        """Fetch and mask in one step, so raw rows never enter graph state."""
        vault = self._vaults.get(state["session_id"])
        sql = state["sql"]
        try:
            rows = self._run_query(sql, _bind_params(state, sql))
        except SQLAlchemyError as err:
            # DB messages can echo data values ("...converting the nvarchar value 'John'..."): mask them
            detail = self._masker.mask_text(str(getattr(err, "orig", err))[:300], vault, use_ner=False).text
            return {"rows": [], "sql_errors": [f"The database rejected the query: {detail}"]}
        column_types = classify_output_columns(sql, self._policy)
        masked, counts = self._masker.mask_rows(rows, column_types or {}, vault)
        return {"rows": db.to_jsonable(masked), "pii_columns": column_types, "pii_masked": dict(counts),
                "sql_errors": []}

    # --- answer ---------------------------------------------------------------------
    def compose_answer(self, state: AgentState) -> dict:
        system = COMPOSE_SYSTEM.format(sequence_number=state["sequence_number"], as_of_date=state["as_of_date"])
        result = json.dumps(state.get("rows", []), default=str)
        messages = [SystemMessage(system),
                    HumanMessage(f"Question: {state['question']}\nQuery result (JSON rows): {result}")]
        response, record = self._call_llm("compose_answer", self._llm, messages, state)
        return {"answer": str(response.content).strip(), "llm_calls": [record]}

    def give_up(self, state: AgentState) -> dict:
        return {"answer": GIVE_UP_MESSAGE}
