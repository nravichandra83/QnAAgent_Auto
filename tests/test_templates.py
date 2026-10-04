"""Core templates against the seeded database: every contract x every core intent."""
import pytest

from agent.db import run_query, to_jsonable
from agent.templates import CORE_TEMPLATES, CUSTOMER_PROFILE, RESOLVE_CONTRACT
from agent.validator import used_params
from tests.golden import AS_OF, GOLDEN, check_rows

pytestmark = pytest.mark.usefixtures("db_available")


@pytest.mark.parametrize("seq", GOLDEN)
@pytest.mark.parametrize("intent", CORE_TEMPLATES)
def test_template_matches_golden(seq, intent):
    contract_id = run_query(RESOLVE_CONTRACT, {"seq": seq})[0]["Id"]
    sql = CORE_TEMPLATES[intent]
    params = {k: v for k, v in {"contract_id": contract_id, "as_of_date": AS_OF}.items() if k in used_params(sql)}
    check_rows(intent, to_jsonable(run_query(sql, params)), GOLDEN[seq])


def test_unknown_sequence_number_resolves_to_nothing():
    assert run_query(RESOLVE_CONTRACT, {"seq": "CT-9999"}) == []


@pytest.mark.parametrize("seq, first_name", [("CT-1001", "John"), ("CT-1003", "Maria"), ("CT-1007", "Priya")])
def test_customer_profile_returns_the_contract_customer(seq, first_name):
    contract_id = run_query(RESOLVE_CONTRACT, {"seq": seq})[0]["Id"]
    rows = run_query(CUSTOMER_PROFILE, {"contract_id": contract_id})
    assert [r["FirstName"] for r in rows] == [first_name]
    assert "SSN" not in rows[0]
