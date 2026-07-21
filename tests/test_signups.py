"""Unit tests for signups.py (email-signup data layer).

Run:  pytest tests/test_signups.py -v

Supabase is never called for real. An autouse fixture stubs requests.post to
raise if invoked at all; any test that needs the network path explicitly
monkeypatches it again with a fake response (mirrors test_sync_db_to_release.py's
subprocess.run stub). A second autouse fixture stubs st.secrets so
insert_signup's lazy secret read never depends on a real secrets.toml.
"""

import ast
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

# Make the repo root importable (signups.py lives there, not under scripts/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import signups  # noqa: E402

EMAIL = "person@example.com"
SOURCE = "test-source"

FAKE_SECRETS = {
    signups.SUPABASE_URL_KEY: "https://fake-project.supabase.co",
    signups.SUPABASE_ANON_KEY_KEY: "fake-anon-key",
}


def _fake_response(status_code: int, text: str = "") -> SimpleNamespace:
    """Mirrors the subset of requests.Response that insert_signup reads."""
    return SimpleNamespace(status_code=status_code, ok=status_code < 400, text=text)


def _forbidden_post(*args, **kwargs):
    raise AssertionError("signups.py must never make a live network call in tests")


def _install_post_stub(monkeypatch, response: SimpleNamespace) -> list:
    """Replaces requests.post with a fake that records every call it receives."""
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return response

    monkeypatch.setattr(signups.requests, "post", fake_post)
    return calls


@pytest.fixture(autouse=True)
def _fake_secrets(monkeypatch):
    monkeypatch.setattr(signups.st, "secrets", FAKE_SECRETS)


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch):
    """Default-deny: any un-stubbed test that reaches requests.post fails loudly."""
    monkeypatch.setattr(signups.requests, "post", _forbidden_post)


# ── Email validation ──────────────────────────────────────────────────────────


def test_invalid_email_is_rejected():
    result = signups.insert_signup("not-an-email", "", SOURCE)
    assert result.ok is False
    assert result.outcome == signups.OUTCOME_INVALID_EMAIL


def test_empty_email_is_rejected():
    result = signups.insert_signup("", "", SOURCE)
    assert result.ok is False
    assert result.outcome == signups.OUTCOME_INVALID_EMAIL


def test_valid_email_passes_validation_and_succeeds(monkeypatch):
    calls = _install_post_stub(monkeypatch, _fake_response(201))
    result = signups.insert_signup(EMAIL, "", SOURCE)
    assert result.ok is True
    assert result.outcome == signups.OUTCOME_SUCCESS
    assert len(calls) == 1


# ── Duplicate email = quiet success ───────────────────────────────────────────


def test_duplicate_email_is_quiet_success_identical_message(monkeypatch):
    _install_post_stub(monkeypatch, _fake_response(201))
    success_result = signups.insert_signup(EMAIL, "", SOURCE)

    _install_post_stub(monkeypatch, _fake_response(409))
    duplicate_result = signups.insert_signup(EMAIL, "", SOURCE)

    assert duplicate_result.ok is True
    assert duplicate_result.outcome == signups.OUTCOME_DUPLICATE
    assert duplicate_result.message == success_result.message


# ── Honeypot ───────────────────────────────────────────────────────────────────


def test_honeypot_filled_is_quiet_success_with_no_network_call(monkeypatch):
    calls = _install_post_stub(monkeypatch, _fake_response(201))
    success_result = signups.insert_signup(EMAIL, "", SOURCE)
    assert len(calls) == 1  # sanity: the success call itself did POST

    spam_result = signups.insert_signup(EMAIL, "", SOURCE, honeypot="bot-filled-this")

    assert spam_result.ok is True
    assert spam_result.outcome == signups.OUTCOME_SPAM
    assert spam_result.message == success_result.message
    assert len(calls) == 1  # unchanged — honeypot made no additional network call


def test_honeypot_short_circuits_before_secrets_or_network():
    # _no_live_network (autouse) leaves requests.post armed to raise if called.
    # A pass here proves the honeypot branch never reaches the network.
    result = signups.insert_signup(EMAIL, "", SOURCE, honeypot="i-am-a-bot")
    assert result.ok is True
    assert result.outcome == signups.OUTCOME_SPAM


# ── Insert failure modes ──────────────────────────────────────────────────────


def test_connection_error_maps_to_network_error(monkeypatch, caplog):
    def raise_connection_error(*a, **kw):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(signups.requests, "post", raise_connection_error)

    with caplog.at_level(logging.ERROR):
        result = signups.insert_signup(EMAIL, "", SOURCE)

    assert result.ok is False
    assert result.outcome == signups.OUTCOME_NETWORK_ERROR
    assert "network error" in caplog.text.lower()


def test_timeout_also_maps_to_network_error(monkeypatch):
    def raise_timeout(*a, **kw):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(signups.requests, "post", raise_timeout)
    result = signups.insert_signup(EMAIL, "", SOURCE)

    assert result.ok is False
    assert result.outcome == signups.OUTCOME_NETWORK_ERROR


def test_401_maps_to_refused(monkeypatch, caplog):
    _install_post_stub(monkeypatch, _fake_response(401))

    with caplog.at_level(logging.ERROR):
        result = signups.insert_signup(EMAIL, "", SOURCE)

    assert result.ok is False
    assert result.outcome == signups.OUTCOME_REFUSED
    assert "refused" in caplog.text.lower()


def test_403_also_maps_to_refused(monkeypatch):
    _install_post_stub(monkeypatch, _fake_response(403))
    result = signups.insert_signup(EMAIL, "", SOURCE)

    assert result.ok is False
    assert result.outcome == signups.OUTCOME_REFUSED


def test_other_non_2xx_maps_to_server_error(monkeypatch, caplog):
    _install_post_stub(monkeypatch, _fake_response(500, text="internal error"))

    with caplog.at_level(logging.ERROR):
        result = signups.insert_signup(EMAIL, "", SOURCE)

    assert result.ok is False
    assert result.outcome == signups.OUTCOME_SERVER_ERROR
    assert "server error" in caplog.text.lower()


# ── Prefer: return=minimal ─────────────────────────────────────────────────────


def test_prefer_return_minimal_header_is_sent(monkeypatch):
    calls = _install_post_stub(monkeypatch, _fake_response(201))
    signups.insert_signup(EMAIL, "", SOURCE)

    assert calls[0]["headers"]["Prefer"] == "return=minimal"
    assert signups.PREFER_MINIMAL == "return=minimal"


# ── Isolation guardrail (pairs with Graphify at P7) ───────────────────────────

FORBIDDEN_MODULES = {
    "analyses",
    "db_sync",
    "storage",
    "analyzer",
    "screen",
    "analyze",
    "brief",
    "init_db",
}


def test_signups_has_no_pipeline_or_db_import_edge():
    """Statically asserts signups.py imports nothing from the analyses.db /
    pipeline layer. Machine-checkable form of the hard isolation guardrail.
    """
    source_path = Path(__file__).resolve().parent.parent / "signups.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [
                alias.name.split(".")[0]
                for alias in node.names
                if alias.name.split(".")[0] in FORBIDDEN_MODULES
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in FORBIDDEN_MODULES:
                found.append(top)

    assert found == [], f"signups.py must not import pipeline/DB modules, found: {found}"
