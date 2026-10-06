"""Streamlit chat UI for the contract query agent.

    streamlit run app/streamlit_app.py

One ContractSession per browser session and selected contract. Switching contract or starting a
new conversation closes the old session, which wipes its PII vault. Abandoned sessions (closed
tabs) are wiped by the vault store's idle TTL.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from agent.config import default_as_of  # noqa: E402
from agent.db import run_query  # noqa: E402
from agent.graph import build_graph  # noqa: E402
from agent.session import ContractNotFound, ContractSession  # noqa: E402
from agent.templates import LIST_CONTRACTS  # noqa: E402
from governance.masker import PiiMasker  # noqa: E402
from governance.policy import load_policy  # noqa: E402
from governance.vault import DEFAULT_VAULT_STORE, Vault  # noqa: E402

logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)
log = logging.getLogger(__name__)

EXAMPLES = [
    "What is the status of this contract?",
    "When is the next payment due?",
    "How much is outstanding?",
    "Who is the customer and what is their email?",
]

st.set_page_config(page_title="Contract Assistant", page_icon=":page_facing_up:", layout="wide")


# --- shared, loaded once per server process --------------------------------------------
@st.cache_resource(show_spinner="Loading the agent...")
def shared_agent():
    policy = load_policy()
    masker = PiiMasker(policy)
    masker.mask_text("Warm up for Robert Smith", Vault())        # loads the NER model now, not on the first question
    return build_graph(policy=policy, masker=masker, vaults=DEFAULT_VAULT_STORE)


@st.cache_data(ttl=300, show_spinner=False)
def list_contracts() -> list[dict]:
    return run_query(LIST_CONTRACTS, {})


# --- per browser session -----------------------------------------------------------------
def open_session(seq: str) -> None:
    old = st.session_state.get("session")
    if old is not None:
        old.close()
    st.session_state.session = ContractSession(seq, app=shared_agent())
    st.session_state.seq = seq
    st.session_state.messages = []


def safe_md(text: str) -> str:
    """Show answers literally: no LaTeX from '$', no HTML from '<...>'."""
    return text.replace("$", "\\$").replace("<", "&lt;")


def render(message: dict, show_details: bool, show_masked: bool) -> None:
    with st.chat_message(message["role"]):
        st.markdown(safe_md(message["content"]))
        if message["role"] != "assistant":
            return
        if show_details and message.get("sql"):
            with st.expander(f"Details: intent {message['intent']}, SQL attempts {message['attempts']}"):
                st.code(message["sql"], language="sql")
                if message["rows"]:
                    st.dataframe(message["rows"], hide_index=True, width="stretch")
                else:
                    st.caption("No rows returned.")
        if show_masked and message.get("masked_question"):
            with st.expander("What the LLM saw (masked)"):
                st.text(f"Question: {message['masked_question']}")
                st.text(f"Answer:   {message['masked_answer']}")
                if message.get("pii"):
                    st.caption("Values masked in the results: " + ", ".join(f"{k} {v}" for k, v in message["pii"].items()))


def ask(question: str, as_of) -> dict:
    session: ContractSession = st.session_state.session
    try:
        result = session.ask(question, as_of)
    except KeyError:                                   # vault expired after the idle TTL
        open_session(st.session_state.seq)
        return {"role": "assistant", "content": "This conversation expired. Please ask your question again."}
    except Exception as err:                          # LLM or database outage; the audit log has the record
        log.exception("Question failed")
        return {"role": "assistant", "content": f"Sorry, something went wrong ({type(err).__name__}). Please try again."}
    state = result.state
    pii = dict(state.get("pii_masked", {}))
    return {
        "role": "assistant",
        "content": result.answer,
        "intent": state.get("intent"),
        "attempts": state.get("sql_attempts", 0),
        "sql": state.get("sql"),
        "rows": session.unmask_rows(state.get("rows", [])),
        "masked_question": result.masked_question,
        "masked_answer": result.masked_answer,
        "pii": pii,
    }


# --- layout ------------------------------------------------------------------------------
try:
    contracts = list_contracts()
except Exception as err:
    st.error(f"Cannot reach the database ({type(err).__name__}). Check DB_CONNECTION_STRING in .env.")
    st.stop()

labels = {c["SequenceNumber"]: f"{c['SequenceNumber']}  ·  {c['ContractType']}  ·  {c['Status']}" for c in contracts}

with st.sidebar:
    st.header("Contract")
    seq = st.selectbox("Contract", list(labels), format_func=labels.get, label_visibility="collapsed")
    as_of = st.date_input("As of date", value=default_as_of())
    st.divider()
    show_details = st.toggle("Show SQL and results")
    show_masked = st.toggle("Show what the LLM saw")
    new_chat = st.button("New conversation", width="stretch")
    st.caption("Personal data is masked before anything is sent to the AI model. "
               "Every question is recorded in the audit log.")

if new_chat or st.session_state.get("seq") != seq:
    try:
        open_session(seq)
    except ContractNotFound as err:
        st.error(str(err))
        st.stop()

st.title("Contract assistant")
st.caption(f"Answers about **{seq}** only, as of {as_of.isoformat()}.")

for message in st.session_state.messages:
    render(message, show_details, show_masked)

pending = None
if not st.session_state.messages:
    cols = st.columns(len(EXAMPLES))
    for col, example in zip(cols, EXAMPLES):
        if col.button(example, width="stretch"):
            pending = example

question = st.chat_input(f"Ask about {seq}...") or pending
if question:
    user_message = {"role": "user", "content": question}
    st.session_state.messages.append(user_message)
    render(user_message, show_details, show_masked)
    with st.spinner("Thinking..."):
        reply = ask(question, as_of)
    st.session_state.messages.append(reply)
    render(reply, show_details, show_masked)
