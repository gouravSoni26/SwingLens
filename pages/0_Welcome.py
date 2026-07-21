"""Streamlit page — Screen 0: Welcome.

Optional entry point for SwingLens. NOT a login/auth page — there are no
accounts, passwords, or sessions here (auth is a deliberately deferred later
phase). This page never gates content: anyone can skip straight to any other
page via the sidebar nav, same as before this page existed. It only invites an
email signup and offers a "continue" link into the app.

The 0_ prefix sorts this above 1_Daily_Screener in Streamlit's native pages/
auto-discovery nav (filesystem multipage — no st.navigation/st.Page wired in
app.py; confirmed at inspection).

Run the app from the repo root:
    streamlit run app.py        # then pick "Welcome" in the sidebar (top item)
"""

import sys
from pathlib import Path

import streamlit as st

# signups.py lives at repo root — make it importable. This file sits in
# <repo>/pages/, so the repo root is one parent up.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from signups import CONSENT_VERSION, insert_signup  # noqa: E402

PAGE_TITLE = "Welcome"
SOURCE_PAGE = "welcome"  # recorded in the source_page column on every insert

DAILY_SCREENER_PAGE = "pages/1_Daily_Screener.py"
# P5 builds this file. _render_privacy_link() below degrades to plain text
# pointing at this path until the page exists, so this page never breaks
# waiting on P5.
PRIVACY_PAGE = "pages/5_Privacy_Policy.py"

FORM_KEY = "welcome_signup_form"
EMAIL_KEY = "welcome_email"
NAME_KEY = "welcome_name"
HONEYPOT_KEY = "welcome_honeypot"
HONEYPOT_LABEL = "Leave this field blank"  # matched by the CSS selector below
CONTINUE_KEY = "welcome_continue"

# ponytail: off-screen positioning, not display:none — a bot that skips
# display:none fields (a common naive honeypot check) still finds and can
# fill this one, so it still works as a real trap. Upgrade path if this stops
# being enough: a server-side timing check (reject submits faster than a
# human could type).
HONEYPOT_CSS = f"""
<style>
div[data-testid="stTextInput"]:has(input[aria-label="{HONEYPOT_LABEL}"]) {{
    position: absolute;
    left: -9999px;
    top: -9999px;
    height: 0;
    overflow: hidden;
}}
</style>
"""

# Names both purposes (feedback/beta contact + future paid-tier interest) and
# must stay in lockstep with CONSENT_VERSION in signups.py — draft copy, final
# wording is Gourav's call.
CONSENT_TEXT = (
    "By submitting, you agree SwingLens may email you about "
    "(1) feedback and beta opportunities, and "
    "(2) a possible future paid tier. No accounts, no spam. "
    f"(Consent version: {CONSENT_VERSION})"
)


def _render_privacy_link() -> None:
    """Links to the privacy page once P5 builds it; plain text until then."""
    try:
        st.page_link(PRIVACY_PAGE, label="Privacy Policy")
    except Exception:
        st.caption(f"Privacy Policy — coming soon ({PRIVACY_PAGE})")


def render_signup_form() -> None:
    """All signup-form logic, isolated so it's callable/testable without page chrome."""
    st.markdown(HONEYPOT_CSS, unsafe_allow_html=True)
    st.caption(CONSENT_TEXT)
    _render_privacy_link()

    with st.form(FORM_KEY, clear_on_submit=False):
        email = st.text_input("Email", key=EMAIL_KEY, placeholder="you@example.com")
        name = st.text_input("Name (optional)", key=NAME_KEY, placeholder="Optional")
        honeypot = st.text_input(HONEYPOT_LABEL, key=HONEYPOT_KEY, label_visibility="collapsed")
        submitted = st.form_submit_button("Notify me", type="primary", use_container_width=True)

    if submitted:
        result = insert_signup(email, name, SOURCE_PAGE, honeypot)
        # success, duplicate, and spam all return ok=True and render identically —
        # the honeypot catch must never be visible to whoever/whatever tripped it.
        if result.ok:
            st.success(result.message)
        else:
            st.error(result.message)


def render_continue_button() -> None:
    """Always visible — this page must never gate access to the rest of the app."""
    if st.button("Continue into SwingLens →", key=CONTINUE_KEY, use_container_width=True):
        st.switch_page(DAILY_SCREENER_PAGE)


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title("👋 Welcome to SwingLens")
    st.caption(
        "Research support for NSE swing trading — this page is optional, "
        "not a login. Jump straight in whenever you like."
    )

    render_continue_button()
    st.divider()

    st.markdown("### Stay in the loop (optional)")
    st.write(
        "Leave your email if you'd like occasional feedback/beta updates, "
        "or a heads-up if a paid tier ever launches."
    )
    render_signup_form()


if __name__ == "__main__":
    main()
