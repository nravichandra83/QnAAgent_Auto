"""End-to-end PII governance: no seeded PII value may appear in anything sent to the LLM
or written to the audit log, while the end user still gets real values back."""
import json
import re

import pytest

from tests.golden import AS_OF

CUSTOMER_SQL = (
    "SELECT cu.FirstName, cu.LastName FROM dbo.Customers cu JOIN dbo.LeaseFinances lf ON lf.CustomerId = cu.Id "
    "WHERE lf.ContractId = :contract_id UNION SELECT cu.FirstName, cu.LastName FROM dbo.Customers cu "
    "JOIN dbo.LoanFinances ln ON ln.CustomerId = cu.Id WHERE ln.ContractId = :contract_id")
CONTACT_SQL = (
    "SELECT cu.Email, cu.Phone, cu.AddressLine1, cu.Zip FROM dbo.Customers cu "
    "JOIN dbo.LeaseFinances lf ON lf.CustomerId = cu.Id WHERE lf.ContractId = :contract_id")
ALIAS_SQL = (
    "SELECT cu.FirstName + ' ' + cu.LastName AS CustomerName FROM dbo.Customers cu "
    "JOIN dbo.LoanFinances ln ON ln.CustomerId = cu.Id WHERE ln.ContractId = :contract_id")
ECHO_ERROR_SQL = (   # SQL Server echoes the value in the conversion error message
    "SELECT CAST(cu.FirstName AS INT) AS n FROM dbo.Customers cu "
    "JOIN dbo.LeaseFinances lf ON lf.CustomerId = cu.Id WHERE lf.ContractId = :contract_id")


def _echo_rows(messages):
    """Fake compose step: answer by repeating the (masked) rows it was given."""
    return "Result: " + messages[-1].content.split("Query result (JSON rows): ", 1)[1]


def _assert_no_pii(text: str, seeded_pii: list[str]) -> None:
    leaked = [v for v in seeded_pii
              if re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", text, re.IGNORECASE)]
    assert not leaked, f"PII reached the LLM/audit: {leaked}"


SCENARIOS = [
    # (contract, question, SQL the 'LLM' writes, values the user must see in the answer)
    ("CT-1001", "Who is the customer?", [CUSTOMER_SQL], ["John", "Carter"]),
    ("CT-1001", "What are the contact details?", [CONTACT_SQL],
     ["john.carter@example.com", "555-0101", "12 Maple Street", "30301"]),
    ("CT-1008", "What is the customer's full name?", [ALIAS_SQL], ["David O'Connor"]),
    ("CT-1001", "Is john.carter@example.com the email on file for John Carter? My SSN is 900-12-3456.",
     [CONTACT_SQL], ["john.carter@example.com"]),
    ("CT-1001", "Show the first name as a number", [ECHO_ERROR_SQL, CUSTOMER_SQL], ["John"]),
]


@pytest.mark.parametrize("seq, question, drafts, visible", SCENARIOS)
def test_no_pii_reaches_llm_but_user_sees_values(make_session, fake_llm, seeded_pii, audit_log,
                                                 seq, question, drafts, visible):
    llm = fake_llm(intent="adhoc", sql_drafts=drafts, answer=_echo_rows)
    result = make_session(seq, llm).ask(question, as_of=AS_OF)

    _assert_no_pii(llm.sent_text(), seeded_pii)                 # nothing raw left for the LLM
    for value in visible:                                        # ... but the user gets real values
        assert value in result.answer, result.answer
    assert "900-12-3456" not in result.answer

    record = json.loads(audit_log.path.read_text(encoding="utf-8").splitlines()[-1])
    _assert_no_pii(json.dumps(record), seeded_pii)
    assert record["pii_guard_masked"] == {}, "earlier layers should leave nothing for the guard"


def test_question_pii_is_masked_before_classification(make_session, fake_llm, seeded_pii):
    llm = fake_llm(intent="status")
    make_session("CT-1001", llm).ask("Status for John Carter, ssn 900-12-3456, phone 555-0101?", as_of=AS_OF)
    classify_payload = "\n".join(m.content for m in llm.calls[0][1])
    _assert_no_pii(classify_payload, seeded_pii)
    assert "<PERSON_1>" in classify_payload and "<SSN_1>" in classify_payload


def test_other_customers_pii_cannot_be_queried(make_session, fake_llm, seeded_pii):
    """Cross-contract SQL is rejected by the validator, so other customers' PII is never fetched."""
    steal = "SELECT cu.FirstName, cu.Email FROM dbo.Customers cu"
    llm = fake_llm(intent="adhoc", sql_drafts=[steal, steal, steal])
    result = make_session("CT-1001", llm).ask("List all customers", as_of=AS_OF)
    assert not result.state.get("rows")
    _assert_no_pii(llm.sent_text(), seeded_pii)


def test_audit_record_shape(make_session, fake_llm, audit_log):
    llm = fake_llm(intent="adhoc", sql_drafts=[CUSTOMER_SQL], answer=_echo_rows)
    make_session("CT-1001", llm).ask("Who is the customer?", as_of=AS_OF)
    record = json.loads(audit_log.path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["outcome"] == "answered" and record["intent"] == "adhoc"
    assert record["pii_columns"] == {"FirstName": "PERSON", "LastName": "PERSON"}
    assert record["pii_masked_output"] == {"PERSON": 2}
    assert [c["node"] for c in record["llm_calls"]] == ["classify_intent", "generate_sql", "compose_answer"]
    assert all(len(c["sha256"]) == 16 and "payload" not in c for c in record["llm_calls"])
    assert "<PERSON_" in record["answer"]


def test_closed_session_cannot_be_used(make_session, fake_llm):
    session = make_session("CT-1001", fake_llm())
    session.close()
    with pytest.raises(KeyError):
        session.ask("status?", as_of=AS_OF)
