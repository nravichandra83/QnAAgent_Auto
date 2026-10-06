"""Streamlit UI tests using streamlit.testing (headless; no browser)."""
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")

pytestmark = pytest.mark.usefixtures("db_available")


def _run():
    at = st_testing.AppTest.from_file(APP, default_timeout=120)
    return at.run()


def test_page_renders_with_contract_list():
    at = _run()
    assert not at.exception, at.exception
    picker = at.sidebar.selectbox[0]
    assert len(picker.options) == 12
    assert picker.value == "CT-1001"
    assert at.title[0].value == "Contract assistant"
    assert len(at.button) >= 4                         # example questions + new conversation


def test_switching_contract_starts_a_new_session():
    at = _run()
    first = at.session_state.session.session_id
    at.sidebar.selectbox[0].select("CT-1003").run()
    assert not at.exception, at.exception
    assert at.session_state.seq == "CT-1003"
    assert at.session_state.session.session_id != first
    assert at.session_state.messages == []


@pytest.mark.live
def test_question_answered_through_ui():
    at = _run()
    at.sidebar.selectbox[0].select("CT-1009").run()
    at.sidebar.date_input[0].set_value(__import__("datetime").date(2026, 10, 1)).run()
    at.chat_input[0].set_value("How much is outstanding?").run()
    assert not at.exception, at.exception
    reply = at.session_state.messages[-1]
    assert reply["role"] == "assistant" and "2,376.00" in reply["content"], reply
