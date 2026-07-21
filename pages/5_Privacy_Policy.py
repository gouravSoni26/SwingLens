"""Streamlit page — Screen 5: Privacy Policy.

Plain-language privacy notice for the email-signup feature on
pages/0_Welcome.py. Not legalese theatre — states what's collected, why, that
it's opt-in, and how to be removed, in sentences a non-technical stranger can
read and understand.

Follows the repo's page convention: main() holds st.set_page_config() as its
first call, invoked via `if __name__ == "__main__"` so this works both as the
Streamlit entrypoint and under multipage nav.

Run the app from the repo root:
    streamlit run app.py        # then pick "Privacy Policy" in the sidebar
"""

import sys
from pathlib import Path

import streamlit as st

# signups.py lives at repo root — make it importable. This file sits in
# <repo>/pages/, so the repo root is one parent up.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from signups import CONSENT_VERSION  # noqa: E402

PAGE_TITLE = "Privacy Policy"
WELCOME_PAGE = "pages/0_Welcome.py"

# PLACEHOLDER — Gourav finalizes. Draft copy only.
OPERATOR_NAME = "Gourav Soni"
CONTACT_EMAIL = "[PLACEHOLDER: your real contact email goes here]"

# What the signup form actually collects — kept as data so the page and any
# future audit can enumerate it, rather than restating it loosely in prose.
DATA_COLLECTED = [
    ("Email", "Required — how we'd reach you."),
    ("Name", "Optional — only recorded if you choose to give it."),
    ("Timestamp", "When you submitted, recorded automatically."),
    ("Source page", 'Which page the form was on (e.g. "welcome"), recorded automatically.'),
]

# Same two purposes as the consent line on the Welcome page (signups.py's
# CONSENT_TEXT) — keep these in sync if either changes.
PURPOSE_FEEDBACK = "To reach out for feedback or beta-testing opportunities."
PURPOSE_PAID_TIER = "To let you know if a future paid tier of SwingLens ever launches."


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title("🔒 Privacy Policy")
    st.caption(f"Consent version: {CONSENT_VERSION}")

    st.markdown("### What we collect")
    for label, desc in DATA_COLLECTED:
        st.markdown(f"- **{label}** — {desc}")
    st.write("Nothing else is collected by this form.")

    st.markdown("### Why we collect it")
    st.markdown(f"- {PURPOSE_FEEDBACK}")
    st.markdown(f"- {PURPOSE_PAID_TIER}")

    st.markdown("### It's opt-in")
    st.write(
        "Nothing is collected unless you choose to submit the signup form on "
        "the Welcome page. SwingLens never requires an email to use any part "
        "of the app — every page stays accessible whether or not you sign up."
    )

    st.markdown("### How to be removed")
    st.write(
        f"Email **{CONTACT_EMAIL}** and ask to be removed. Removal is handled "
        "manually in this version — there is no self-serve unsubscribe link yet."
    )

    st.markdown("### Who's responsible")
    st.write(
        f"**{OPERATOR_NAME}** operates SwingLens and is the sole contact for "
        f"privacy questions or removal requests, at {CONTACT_EMAIL}."
    )

    st.divider()
    st.page_link(WELCOME_PAGE, label="← Back to Welcome")


if __name__ == "__main__":
    main()
