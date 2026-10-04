"""Graph routing through a ContractSession, with a fake LLM and the real seeded database."""
from datetime import date

import pytest

from agent.nodes import GIVE_UP_MESSAGE
from agent.session import ContractNotFound
from agent.state import CORE_INTENTS
from tests.golden import AS_OF, GOLDEN, check_rows


@pytest.mark.parametrize("seq", GOLDEN)
@pytest.mark.parametrize("intent", CORE_INTENTS)
def test_core_intents_use_templates(make_session, fake_llm, seq, intent):
    llm = fake_llm(intent=intent, answer="composed")
    result = make_session(seq, llm).ask("question", as_of=AS_OF)
    check_rows(intent, result.state["rows"], GOLDEN[seq])
    assert result.answer == "composed"
    assert "SqlDraft" not in [name for name, _ in llm.calls], "core intents must not use LLM-written SQL"


def test_unknown_contract_raises_before_llm(make_session, fake_llm):
    llm = fake_llm()
    with pytest.raises(ContractNotFound, match="couldn't find"):
        make_session("CT-9999", llm)
    assert llm.calls == []


def test_adhoc_valid_sql_runs(make_session, fake_llm):
    llm = fake_llm(intent="adhoc", sql_drafts=[
        "SELECT c.CommencementDate FROM dbo.Contracts c WHERE c.Id = :contract_id"])
    result = make_session("CT-1001", llm).ask("When did it commence?", as_of=AS_OF)
    assert result.state["rows"] == [{"CommencementDate": "2026-05-01"}]
    assert result.state["sql_attempts"] == 1


def test_adhoc_unsafe_sql_retries_then_gives_up(make_session, fake_llm):
    bad = "SELECT * FROM dbo.Contracts"
    llm = fake_llm(intent="adhoc", sql_drafts=[bad, bad, bad])
    result = make_session("CT-1001", llm).ask("Show everything", as_of=AS_OF)
    assert result.answer == GIVE_UP_MESSAGE
    assert result.state["sql_attempts"] == 3
    assert not result.state.get("rows")


def test_adhoc_repairs_after_validation_error(make_session, fake_llm):
    llm = fake_llm(intent="adhoc", sql_drafts=[
        "SELECT * FROM dbo.Contracts WHERE Id = :contract_id",
        "SELECT c.ContractType FROM dbo.Contracts c WHERE c.Id = :contract_id",
    ])
    result = make_session("CT-1003", llm).ask("What type is it?", as_of=AS_OF)
    assert result.state["rows"] == [{"ContractType": "Loan"}]
    repair_prompt = llm.calls[2][1][-1].content
    assert "SELECT *" in repair_prompt


def test_adhoc_repairs_after_database_error(make_session, fake_llm):
    llm = fake_llm(intent="adhoc", sql_drafts=[
        "SELECT c.NoSuchColumn FROM dbo.Contracts c WHERE c.Id = :contract_id",
        "SELECT c.WorkflowStatus FROM dbo.Contracts c WHERE c.Id = :contract_id",
    ])
    result = make_session("CT-1007", llm).ask("Where is it in the workflow?", as_of=AS_OF)
    assert result.state["rows"] == [{"WorkflowStatus": "Documents Submitted"}]
    assert result.state["sql_attempts"] == 2


def test_as_of_date_is_bound(make_session, fake_llm):
    llm = fake_llm(intent="outstanding_amount")
    result = make_session("CT-1001", llm).ask("outstanding?", as_of=date(2026, 9, 2))
    # As of 2026-09-02 only the 09-01 receivable is due and unpaid
    assert result.state["rows"][0]["OutstandingTotal"] == "1080.00"


def test_history_carries_masked_turns(make_session, fake_llm):
    llm = fake_llm(intent="status", answer="It is commenced.")
    session = make_session("CT-1001", llm)
    session.ask("What is the status?", as_of=AS_OF)
    session.ask("And for John Carter?", as_of=AS_OF)
    second_classify = [msgs for name, msgs in llm.calls if name == "IntentDecision"][1]
    contents = [m.content for m in second_classify]
    assert "What is the status?" in contents and "It is commenced." in contents
    assert all("John" not in c for c in contents)
