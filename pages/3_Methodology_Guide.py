"""Streamlit page — Screen 3: Methodology Guide.

Renders skills/nse-setup-analysis/methodology.md (Saif sir's training framework)
into 7 fixed tabs. The methodology file is the single source of truth for analysis
rules (CLAUDE.md: never hardcode analysis rules elsewhere) — this page only reads
and displays it, it never restates or interprets the rules.

``## N. Title`` sections render as markdown; ``### N.M`` sub-sections render as
collapsed expanders. A PAYWALL_ENABLED flag (default False) gates tabs 2–7 behind
an upgrade notice for a future tiered offering.

RESEARCH SUPPORT ONLY. This is reference documentation for manual study — never a
trade signal, prediction, or confidence score (CLAUDE.md governance constraints).

Run the app from the repo root:
    streamlit run app.py        # then pick "Methodology Guide" in the sidebar
"""

import re
from pathlib import Path
from typing import NamedTuple

import streamlit as st

# methodology.md lives under the repo regardless of CWD. This file sits in
# <repo>/pages/, so the repo root is two parents up (mirrors 2_Ticker_Analysis.py).
REPO_ROOT = Path(__file__).resolve().parent.parent
METHODOLOGY_PATH = REPO_ROOT / Path("skills/nse-setup-analysis/methodology.md")

# When True, every tab except the free one shows an upgrade notice instead of
# content. Default False — the full guide is available.
PAYWALL_ENABLED = False

PAGE_TITLE = "NSE Methodology Guide"
GOVERNANCE_BANNER = (
    "Reference documentation for manual study — **not trade signals**. "
    "Rules sourced from `methodology.md` (Saif sir's training notes)."
)
PAYWALL_MESSAGE = "🔒 Upgrade to SwingLens Pro"
MISSING_FILE_ERROR = (
    f"methodology.md not found at {METHODOLOGY_PATH}. This page cannot render without it."
)

FRONTMATTER_DELIMITER = "---"

# Tab label → the ## section numbers it renders, in display order. Single source
# of truth for the tab layout. The first tab is free; the rest are paywalled when
# PAYWALL_ENABLED is True.
TAB_SPECS = (
    ("📐 Framework", (1, 2)),
    ("📈 Trend", (3,)),
    ("🧱 S/R & Breakouts", (4, 5, 6)),
    ("📊 Patterns & Volume", (7, 8, 9, 10)),
    ("🔢 Fibonacci", (11,)),
    ("📉 Indicators", (12,)),
    ("✅ Rules & Pending", (13, 14, 15)),
)
FREE_TAB_INDEX = 0

# Matches "## 3. Title" → captures the section integer (3). The trailing dot keeps
# it from matching a bare "## Heading" with no number.
_SECTION_RE = re.compile(r"^##\s+(\d+)\.")
# Matches "### 3.1 Title" — only used as a boolean test, so the number is not
# captured.
_SUBSECTION_RE = re.compile(r"^###\s+(?:\d+)\.\d+")


class Section(NamedTuple):
    """One ## section: its number, its intro markdown, and its sub-sections."""

    number: int
    intro_md: str
    subsections: list[tuple[str, str]]  # (expander label, body markdown)


# ── Parsing (pure — no Streamlit, so it is unit-testable headless) ────────────


def strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block (between two --- lines).

    Returns text unchanged when it does not open with a frontmatter delimiter.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_DELIMITER:
            return "".join(lines[index + 1 :])
    return text  # no closing delimiter — leave it alone rather than eat the file


def parse_sections(text: str) -> dict[int, Section]:
    """Parse markdown into {section_number: Section}.

    A ``## N.`` heading opens section N; its heading line plus any prose before the
    first ``### N.M`` becomes intro_md. Each ``### N.M`` heading opens a sub-section
    keyed to the enclosing ``##`` section (the most recently opened one). The real
    file is well-formed, so a sub-section's N.M prefix always matches its enclosing
    section.
    """
    sections: dict[int, Section] = {}
    current: int | None = None
    intro: list[str] = []
    subs: list[tuple[str, str]] = []
    sub_label: str | None = None
    sub_body: list[str] = []

    def _flush_sub() -> None:
        nonlocal sub_label, sub_body
        if sub_label is not None:
            subs.append((sub_label, "".join(sub_body).strip()))
            sub_label, sub_body = None, []

    def _flush_section() -> None:
        nonlocal intro, subs
        if current is not None:
            _flush_sub()
            sections[current] = Section(current, "".join(intro).rstrip(), subs)
            intro, subs = [], []

    for line in text.splitlines(keepends=True):
        section_match = _SECTION_RE.match(line)
        if section_match:
            _flush_section()
            current = int(section_match.group(1))
            intro = [line]
            continue
        if current is None:
            continue  # content before the first numbered section (title block)
        if _SUBSECTION_RE.match(line):
            _flush_sub()
            sub_label = line.lstrip("#").strip()
            sub_body = []
            continue
        if sub_label is not None:
            sub_body.append(line)
        else:
            intro.append(line)

    _flush_section()
    return sections


# ── Rendering ────────────────────────────────────────────────────────────────


def render_section(section: Section) -> None:
    """Render one section: intro markdown, then each sub-section as an expander."""
    if section.intro_md:
        st.markdown(section.intro_md)
    for label, body in section.subsections:
        with st.expander(label, expanded=False):
            st.markdown(body)


def render_tab(index: int, section_numbers: tuple[int, ...], sections: dict[int, Section]) -> None:
    """Render one tab's sections, or the paywall notice when gated."""
    if PAYWALL_ENABLED and index != FREE_TAB_INDEX:
        st.warning(PAYWALL_MESSAGE)
        return
    for number in section_numbers:
        section = sections.get(number)
        if section is not None:
            render_section(section)


# ── UI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title(PAGE_TITLE)
    st.info(GOVERNANCE_BANNER)

    if not METHODOLOGY_PATH.exists():
        st.error(MISSING_FILE_ERROR)
        st.stop()

    sections = parse_sections(strip_frontmatter(METHODOLOGY_PATH.read_text(encoding="utf-8")))

    tabs = st.tabs([label for label, _ in TAB_SPECS])
    for index, (tab, (_, section_numbers)) in enumerate(zip(tabs, TAB_SPECS)):
        with tab:
            render_tab(index, section_numbers, sections)


if __name__ == "__main__":
    main()
