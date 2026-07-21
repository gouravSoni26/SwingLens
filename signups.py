"""Email-signup data layer for SwingLens.

ISOLATION INVARIANT: this module imports NOTHING from the analyses.db / pipeline
side (no storage, db_sync, analyzer, screen, analyze, brief, init_db). It talks
only to Supabase over HTTPS. Graphify verifies this has no import edge to the
pipeline at P7 — keep it that way.

Single app-side surface: one INSERT into the `email_signups` table via a raw
PostgREST POST with the anon key. No supabase-py — `requests` is already a
pinned dep and the auth is three headers.

Secrets are read LAZILY inside insert_signup (never at import), so the module
stays importable in a test env with no secrets configured.

RLS shape this code is written against (see Step 1 SQL): anon has an INSERT-only
policy and NO select policy. Consequences baked in here:
  - Prefer: return=minimal — we must NOT ask for the row back; the read-back
    would be blocked by RLS and make a good insert look failed.
  - Duplicate email surfaces as HTTP 409 (unique violation); we treat it as a
    quiet success — one row, no error shown to the user.
"""

import logging
import re
from dataclasses import dataclass

import requests
import streamlit as st

from signup_config import SUPABASE_ANON_KEY_KEY, SUPABASE_URL_KEY

logger = logging.getLogger(__name__)

# ── Constants (no magic strings/numbers) ─────────────────────────────────────
TABLE = "email_signups"
REST_PATH = f"/rest/v1/{TABLE}"
PREFER_MINIMAL = "return=minimal"  # do NOT request the row back — RLS blocks the read
REQUEST_TIMEOUT_SECONDS = 10

# Current consent copy the user is shown. The table requires consent_version
# NOT NULL and the insert_signup signature doesn't carry it, so it lives here as
# the single source of truth; P4's UI must render the copy that matches this tag.
CONSENT_VERSION = "2026-07-v1"

# Pragmatic email check — one @, a dot in the domain, no whitespace. Not RFC 5322;
# the real validation is the user receiving anything we ever send.
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Machine-readable outcome tags. `ok` (in SignupResult) drives the UI; `outcome`
# lets the caller distinguish cases — notably SPAM, which looks like success to
# the user but is logged internally (P4 reads .outcome to wire it right).
OUTCOME_SUCCESS = "success"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_SPAM = "spam"
OUTCOME_INVALID_EMAIL = "invalid_email"
OUTCOME_NETWORK_ERROR = "network_error"
OUTCOME_REFUSED = "refused"
OUTCOME_SERVER_ERROR = "server_error"

# Plain user-facing text. SUCCESS/DUPLICATE/SPAM share the same thank-you so a
# bot can't tell its honeypot fired and a repeat signup can't tell it's a repeat.
_THANK_YOU = "Thanks — you're on the list."
_MESSAGES = {
    OUTCOME_SUCCESS: _THANK_YOU,
    OUTCOME_DUPLICATE: _THANK_YOU,
    OUTCOME_SPAM: _THANK_YOU,
    OUTCOME_INVALID_EMAIL: "Please enter a valid email address.",
    OUTCOME_NETWORK_ERROR: "Couldn't reach the server — please try again.",
    OUTCOME_REFUSED: "Signup is temporarily unavailable.",
    OUTCOME_SERVER_ERROR: "Something went wrong — please try again.",
}


@dataclass(frozen=True)
class SignupResult:
    ok: bool       # True → UI shows `message` as a thank-you; False → shows it as an error
    outcome: str   # one of the OUTCOME_* tags — how the caller distinguishes cases
    message: str   # plain user-facing text


def _result(outcome: str, *, ok: bool) -> SignupResult:
    return SignupResult(ok=ok, outcome=outcome, message=_MESSAGES[outcome])


def _redact(email: str) -> str:
    """First char + domain, for PII-safe logs: 'a***@example.com'."""
    email = email.strip()
    local, _, domain = email.partition("@")
    head = local[:1] if local else ""
    return f"{head}***@{domain}" if domain else "***"


def insert_signup(email: str, name: str, source_page: str, honeypot: str = "") -> SignupResult:
    """Insert one signup. Never raises — every outcome is a logged SignupResult.

    honeypot: a hidden form field. If a bot fills it, we log spam and return the
    same thank-you as success (don't teach the bot); no row is written.
    """
    try:
        # 1. Honeypot — hidden field should be empty for a real human.
        if honeypot and honeypot.strip():
            logger.warning("signup honeypot tripped (source=%s) — dropped as spam", source_page)
            return _result(OUTCOME_SPAM, ok=True)

        # 2. Validate email at the trust boundary.
        if not email or not EMAIL_REGEX.match(email.strip()):
            logger.warning("signup rejected: malformed email %r (source=%s)", email, source_page)
            return _result(OUTCOME_INVALID_EMAIL, ok=False)

        # 3. Lazy secret read — a missing key is a deploy misconfig, logged loud.
        try:
            base_url = str(st.secrets[SUPABASE_URL_KEY]).rstrip("/")
            anon_key = str(st.secrets[SUPABASE_ANON_KEY_KEY])
        except KeyError as exc:
            logger.error("signup misconfigured — missing secret %s", exc)
            return _result(OUTCOME_SERVER_ERROR, ok=False)

        payload = {
            "email": email.strip(),
            "source_page": source_page,
            "consent_version": CONSENT_VERSION,
        }
        if name and name.strip():
            payload["name"] = name.strip()

        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
            "Prefer": PREFER_MINIMAL,
        }

        resp = requests.post(
            base_url + REST_PATH,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        # 4. Map the response. Check 409 explicitly (resp.ok is False for it, but
        # be explicit), then 2xx success, then auth/other failures.
        if resp.status_code == 409:
            logger.info("signup duplicate %s (source=%s) — quiet success", _redact(email), source_page)
            return _result(OUTCOME_DUPLICATE, ok=True)
        if resp.ok:
            logger.info("signup ok %s (source=%s)", _redact(email), source_page)
            return _result(OUTCOME_SUCCESS, ok=True)
        if resp.status_code in (401, 403):
            logger.error("signup refused (HTTP %s) — check anon key / RLS policy", resp.status_code)
            return _result(OUTCOME_REFUSED, ok=False)
        logger.error("signup server error (HTTP %s): %s", resp.status_code, resp.text[:200])
        return _result(OUTCOME_SERVER_ERROR, ok=False)

    # requests parent — Timeout and ConnectionError both land here.
    except requests.RequestException as exc:
        logger.error("signup network error: %s", exc)
        return _result(OUTCOME_NETWORK_ERROR, ok=False)
    # Contract: nothing escapes this boundary. Any unexpected error is logged loud.
    except Exception as exc:  # noqa: BLE001 — boundary guard, see docstring
        logger.error("signup unexpected error: %s", exc)
        return _result(OUTCOME_SERVER_ERROR, ok=False)
