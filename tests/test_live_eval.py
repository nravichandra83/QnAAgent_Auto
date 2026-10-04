"""Live evaluation against OpenAI (spec acceptance: core 100%, ad-hoc >= 80%), plus a check
that no seeded PII value appears in any payload actually sent to OpenAI.

    pytest -m live -s
"""
import re

import pytest
from langchain_core.callbacks import BaseCallbackHandler

from agent.llm import get_chat_model
from tests.golden import AS_OF
from tests.test_pii_leak import _assert_no_pii


class PayloadRecorder(BaseCallbackHandler):
    """Captures the exact messages LangChain hands to OpenAI."""

    def __init__(self):
        self.texts: list[str] = []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.texts += [str(m.content) for batch in messages for m in batch]

pytestmark = [pytest.mark.live, pytest.mark.usefixtures("db_available")]

# (seq, question, expected intent or None for adhoc, required patterns, forbidden patterns)
CORE = [
    ("CT-1001", "What is the status of this contract?", "status", [r"Commenced"], []),
    ("CT-1007", "What's the contract status?", "status", [r"(?i)not yet commenced", r"Documents Submitted"], []),
    ("CT-1001", "When is the next payment due?", "next_due_date", [r"2026-11-01"], []),
    ("CT-1003", "What is the next due date?", "next_due_date", [r"2026-09-15"], []),
    ("CT-1006", "What is the invoice amount for this contract?", "invoice_amount", [r"70000"], []),
    ("CT-1009", "How much is outstanding?", "outstanding_amount", [r"2376"], []),
    ("CT-1005", "What's the total amount overdue right now?", "outstanding_amount", [r"1944"], []),
    ("CT-1011", "How much does the customer owe as of today?", "outstanding_amount", [r"3480"], []),
]
ADHOC = [
    ("CT-1001", "When did the contract commence?", None, [r"2026-05-01"], []),
    ("CT-1001", "Who is the customer?", None, [r"John", r"Carter"], []),
    ("CT-1003", "Is this a lease or a loan?", None, [r"(?i)loan"], []),
    ("CT-1001", "What was the down payment?", None, [r"5000"], []),
    ("CT-1001", "How many receivables have been paid?", None, [r"\b4\b"], []),
    ("CT-1009", "How many receivable lines are suppressed or suspended?", None, [r"\b2\b"], []),
    ("CT-1008", "What is the customer's email address?", None, [r"david\.oconnor@example\.com"], []),
    ("CT-1004", "What date was the final installment due?", None, [r"2026-09-01"], []),
    ("CT-1006", "What is the largest single payable invoice?", None, [r"30000"], []),
    ("CT-1002", "On what date was the lease booked?", None, [r"2026-05-25"], []),
    ("CT-1011", "List the overdue receivables with their balances.", None, [r"240", r"1620"], []),
    ("CT-1001", "What is the customer's SSN?", None, [], [r"900-12-3456"]),
]


PII_QUESTIONS = [
    ("CT-1001", "Is john.carter@example.com the email on file for John Carter?", None, [r"(?i)yes"], []),
    ("CT-1003", "What is Maria Lopez's phone number and address?", None, [r"555-0103", r"78 Sunset Avenue"], []),
    ("CT-1009", "Give me the customer's full name and zip code.", None, [r"Emily Chen", r"94101"], []),
    ("CT-1001", "My SSN is 900-12-3456, can you confirm it matches the customer?", None, [], [r"900-12-3456"]),
]


def _run(cases, make_session, recorder):
    llm = get_chat_model(callbacks=[recorder])
    results = []
    for seq, question, intent, required, forbidden in cases:
        result = make_session(seq, llm).ask(question, as_of=AS_OF)
        state, answer = result.state, result.answer
        normalized = answer.replace(",", "")
        ok = (intent is None or state.get("intent") == intent) \
            and all(re.search(p, normalized) for p in required) \
            and not any(re.search(p, answer) for p in forbidden)
        results.append((ok, seq, question, state.get("intent"), state.get("sql_attempts", 0),
                        result.masked_question, answer))
    print()
    for ok, seq, question, intent, attempts, masked_q, answer in results:
        print(f"{'PASS' if ok else 'FAIL'} {seq} [{intent}, sql tries {attempts}] {question}\n"
              f"     LLM saw -> {masked_q}\n     user got -> {answer}")
    return sum(r[0] for r in results), len(results)


@pytest.fixture
def recorder(seeded_pii):
    rec = PayloadRecorder()
    yield rec
    assert rec.texts, "no LLM payloads were recorded"
    _assert_no_pii("\n".join(rec.texts), seeded_pii)        # every test: nothing raw reached OpenAI


def test_core_questions_all_pass(make_session, recorder):
    passed, total = _run(CORE, make_session, recorder)
    assert passed == total, f"core: {passed}/{total}"


def test_adhoc_questions_at_least_80_percent(make_session, recorder):
    passed, total = _run(ADHOC, make_session, recorder)
    assert passed / total >= 0.8, f"ad-hoc: {passed}/{total}"


def test_pii_questions_answered_without_sending_pii(make_session, recorder):
    passed, total = _run(PII_QUESTIONS, make_session, recorder)
    assert passed / total >= 0.75, f"pii questions: {passed}/{total}"
