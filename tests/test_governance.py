"""Unit tests for the governance components (no database, no LLM)."""
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from governance.guard import EgressGuard, PiiLeakError
from governance.lineage import classify_output_columns
from governance.masker import REDACTED, PiiMasker
from governance.policy import load_policy
from governance.vault import Vault, VaultStore

POLICY = load_policy()


@pytest.fixture(scope="module")
def masker():
    return PiiMasker(POLICY)


@pytest.fixture
def vault():
    v = Vault()
    for value, entity in [("John", "PERSON"), ("Carter", "PERSON"), ("John Carter", "PERSON"),
                          ("john.carter@example.com", "EMAIL"), ("555-0101", "PHONE"),
                          ("12 Maple Street", "ADDRESS"), ("30301", "ZIP")]:
        v.register_known(value, entity)
    return v


# --- vault ----------------------------------------------------------------------------
def test_tokens_are_stable_and_case_insensitive():
    v = Vault()
    assert v.tokenize("John Carter", "PERSON") == "<PERSON_1>"
    assert v.tokenize("john  carter", "PERSON") == "<PERSON_1>"
    assert v.tokenize("Maria", "PERSON") == "<PERSON_2>"
    assert v.tokenize("a@example.com", "EMAIL") == "<EMAIL_1>"
    assert v.value_of("<PERSON_1>") == "John Carter"


def test_vault_repr_never_shows_values(vault):
    vault.tokenize("John Carter", "PERSON")
    assert "John" not in repr(vault) and "redacted" in repr(vault)


def test_vault_store_fails_closed_and_wipes():
    store = VaultStore()
    v = store.create("s1")
    v.tokenize("John", "PERSON")
    store.close("s1")
    assert len(v) == 0
    with pytest.raises(KeyError):
        store.get("s1")


def test_vault_store_expires_idle_sessions():
    store = VaultStore(ttl_seconds=-1)
    store.create("s1")
    with pytest.raises(KeyError):
        store.get("s1")


# --- text masking ---------------------------------------------------------------------
@pytest.mark.parametrize("text, entity", [
    ("my ssn is 900-12-3456", "SSN"),
    ("ssn 900 12 3456 please", "SSN"),
    ("mail me at jane.doe@corp.example.org", "EMAIL"),
    ("call (404) 555-0199", "PHONE"),
    ("call +1 404-555-0199 now", "PHONE"),
    ("local 555-0123", "PHONE"),
    ("card 4111 1111 1111 1111", "CREDIT_CARD"),
])
def test_regex_detectors(masker, text, entity):
    result = masker.mask_text(text, Vault(), use_ner=False)
    assert result.counts[entity] == 1, result.text
    assert f"<{entity}_1>" in result.text


@pytest.mark.parametrize("text", [
    "What is the outstanding amount for CT-1001 as of 2026-10-01?",
    "The invoice total is 45,000.00 USD with tax 3,600.00.",
    "Receivable 74 was due on 2026-11-01 for 1620.00.",
    "card 4111 1111 1111 1112",                       # fails the Luhn check
    "Is the contract Commenced or PaidOff?",
])
def test_no_false_positives_on_domain_text(masker, text):
    result = masker.mask_text(text, Vault())
    assert result.text == text, result.text


def test_known_values_mask_longest_first(masker, vault):
    result = masker.mask_text("Does JOHN CARTER live at 12 maple street, zip 30301?", vault, use_ner=False)
    assert result.text == "Does <PERSON_1> live at <ADDRESS_1>, zip <ZIP_1>?"


def test_same_value_same_token_across_texts(masker, vault):
    a = masker.mask_text("email john.carter@example.com", vault).text
    b = masker.mask_text("is JOHN.CARTER@EXAMPLE.COM correct?", vault).text
    assert a == "email <EMAIL_1>" and b == "is <EMAIL_1> correct?"


def test_possessive_stays_outside_token(masker, vault):
    result = masker.mask_text("What is John Carter's phone?", vault)
    assert result.text == "What is <PERSON_1>'s phone?"
    assert masker.unmask(result.text, vault) == "What is John Carter's phone?"


def test_existing_tokens_are_not_remasked(masker, vault):
    once = masker.mask_text("John at 555-0101", vault).text
    assert masker.mask_text(once, vault).text == once


def test_ner_masks_names_not_in_the_vault(masker):
    pytest.importorskip("presidio_analyzer")
    result = masker.mask_text("Is Robert Smith the cosigner on CT-1001?", Vault())
    assert "Robert" not in result.text and "<PERSON_1>" in result.text
    assert "CT-1001" in result.text


# --- rows -----------------------------------------------------------------------------
def test_mask_rows_by_column_type_and_value_scan(masker, vault):
    rows = [{"CustomerName": "John Carter", "Note": "reach john.carter@example.com", "Amount": 1080, "Due": None}]
    masked, counts = masker.mask_rows(rows, {"CustomerName": "PERSON"}, vault)
    assert masked == [{"CustomerName": "<PERSON_1>", "Note": "reach <EMAIL_1>", "Amount": 1080, "Due": None}]
    assert counts == {"PERSON": 1, "EMAIL": 1}


# --- unmasking ------------------------------------------------------------------------
def test_unmask_respects_reveal_policy(masker):
    v = Vault()
    person, ssn = v.tokenize("John Carter", "PERSON"), v.tokenize("900-12-3456", "SSN")
    text = f"{person} has SSN {ssn}; <PERSON_99> is unknown"
    assert masker.unmask(text, v) == f"John Carter has SSN {REDACTED}; <PERSON_99> is unknown"


# --- lineage --------------------------------------------------------------------------
@pytest.mark.parametrize("sql, expected", [
    ("SELECT cu.FirstName, cu.Email FROM dbo.Customers cu", {"FirstName": "PERSON", "Email": "EMAIL"}),
    ("SELECT cu.FirstName + ' ' + cu.LastName AS CustomerName, cu.CustomerType FROM dbo.Customers cu",
     {"CustomerName": "PERSON"}),
    ("SELECT UPPER(cu.Phone) AS p FROM dbo.Customers cu", {"p": "PHONE"}),
    ("WITH x AS (SELECT cu.AddressLine1 AS Street FROM dbo.Customers cu) SELECT x.Street AS Addr FROM x",
     {"Addr": "ADDRESS"}),
    ("SELECT c.Status FROM dbo.Contracts c WHERE c.Id = :contract_id", {}),
])
def test_lineage_classifies_output_columns(sql, expected):
    assert classify_output_columns(sql, POLICY) == expected


def test_lineage_failure_returns_none():
    assert classify_output_columns("SELEC broken", POLICY) is None


# --- egress guard ---------------------------------------------------------------------
def test_guard_masks_leaks_in_mask_mode(masker, vault):
    guard = EgressGuard(masker, "mask")
    messages = [SystemMessage("You are helpful."), HumanMessage("Rows: [{\"Email\": \"john.carter@example.com\"}]")]
    cleaned, findings = guard.check(messages, vault)
    assert findings == {"EMAIL": 1}
    assert "john.carter" not in cleaned[1].content and "<EMAIL_1>" in cleaned[1].content
    assert messages[1].content.startswith("Rows: [{\"Email\": \"john")   # originals untouched


def test_guard_blocks_in_block_mode(masker, vault):
    guard = EgressGuard(masker, "block")
    with pytest.raises(PiiLeakError) as err:
        guard.check([HumanMessage("SSN 900-12-3456")], vault)
    assert "900-12" not in str(err.value)


def test_guard_passes_clean_payloads(masker, vault):
    cleaned, findings = EgressGuard(masker, "block").check([HumanMessage("Outstanding is 2,160.00")], vault)
    assert not findings and cleaned[0].content == "Outstanding is 2,160.00"


# --- policy ---------------------------------------------------------------------------
def test_policy_loads_and_ssn_is_never_revealed():
    assert POLICY.reveal["SSN"] is False and POLICY.reveal["PERSON"] is True
    assert ("customers", "ssn") in POLICY.restricted_columns
    assert POLICY.is_allowed("CT-1001") and POLICY.is_allowed("commenced")
