"""LangGraph wiring. The graph sees masked data only; masking, unmasking and audit happen
in the session layer around it (agent/session.py)."""
from typing import Callable

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from agent import db
from agent.config import get_settings
from agent.nodes import AgentNodes
from agent.state import CORE_INTENTS, AgentState
from governance.masker import PiiMasker
from governance.policy import Policy, load_policy
from governance.vault import DEFAULT_VAULT_STORE, VaultStore


def build_graph(llm: BaseChatModel | None = None,
                *,
                policy: Policy | None = None,
                masker: PiiMasker | None = None,
                vaults: VaultStore = DEFAULT_VAULT_STORE,
                run_query: Callable[..., list[dict]] = db.run_query,
                max_sql_retries: int | None = None):
    if llm is None:
        from agent.llm import get_chat_model
        llm = get_chat_model()
    policy = policy or load_policy()
    masker = masker or PiiMasker(policy)
    if max_sql_retries is None:
        max_sql_retries = get_settings().max_sql_retries
    nodes = AgentNodes(llm, policy, masker, vaults, run_query)

    def after_classify(state: AgentState) -> str:
        return "core" if state["intent"] in CORE_INTENTS else "adhoc"

    def retry_or_give_up(state: AgentState) -> str:
        return "retry" if state.get("sql_attempts", 0) <= max_sql_retries else "give up"

    def after_validate(state: AgentState) -> str:
        return retry_or_give_up(state) if state.get("sql_errors") else "valid"

    def after_execute(state: AgentState) -> str:
        if not state.get("sql_errors"):
            return "ok"
        return retry_or_give_up(state) if state["intent"] == "adhoc" else "give up"

    graph = StateGraph(AgentState)
    for name in ("classify_intent", "run_template", "generate_sql", "validate_sql",
                 "execute_sql", "compose_answer", "give_up"):
        graph.add_node(name, getattr(nodes, name))

    # Path maps: route label -> next node (the labels also annotate the drawn graph)
    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges("classify_intent", after_classify,
                                {"core": "run_template", "adhoc": "generate_sql"})
    graph.add_edge("run_template", "execute_sql")
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges("validate_sql", after_validate,
                                {"valid": "execute_sql", "retry": "generate_sql", "give up": "give_up"})
    graph.add_conditional_edges("execute_sql", after_execute,
                                {"ok": "compose_answer", "retry": "generate_sql", "give up": "give_up"})
    graph.add_edge("compose_answer", END)
    graph.add_edge("give_up", END)
    return graph.compile()
