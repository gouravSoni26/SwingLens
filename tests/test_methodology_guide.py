"""Tests for pages/3_Methodology_Guide.py parsing helpers.

The page renders methodology.md into fixed tabs, so the two things that can
silently break are the frontmatter strip (leaking YAML into the UI) and the
section parser (a sub-section landing under the wrong parent). Both are pure
functions exercised against a synthetic methodology snippet — no Streamlit UI.

streamlit is imported by the page module at top level; if it is not installed in
the test environment the whole module is skipped. Run from the repo root:
    trading-app/Scripts/python.exe -m pytest tests/test_methodology_guide.py -v
"""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("streamlit")  # page module imports streamlit at top level

# Load the page module by path (filename starts with a digit, so it is not a
# normal import name).
_MODULE_PATH = Path(__file__).resolve().parent.parent / "pages" / "3_Methodology_Guide.py"
_spec = importlib.util.spec_from_file_location("methodology_guide_page", _MODULE_PATH)
page = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(page)


# Synthetic methodology with the same shape as the real file: frontmatter, a
# title block, sections 1–15, and sub-sections only under 3 and 12.
_SAMPLE = """---
version: v1.0
known_gaps:
  - "placeholder"
---

# methodology.md — title block

## 1. Core Framework
Intro prose for section one.

## 2. Timeframe Roles
Intro prose for section two.

## 3. Trend Analysis

Intro before sub-sections.

### 3.1 What is a Trend?
Body of 3.1.

### 3.2 LTRP
Body of 3.2.

## 4. Support
## 5. Breakouts
## 6. Polarity
## 7. Trendlines
## 8. Patterns
## 9. Volume
## 10. Gaps
## 11. Fibonacci

## 12. Indicators

### 12.1 Moving Averages
Body of 12.1.

### 12.2 RSI
Body of 12.2.

## 13. Summary Rules
## 14. Disqualifiers
## 15. Pending
"""


def test_parse_sections_finds_all_15():
    sections = page.parse_sections(page.strip_frontmatter(_SAMPLE))

    assert sorted(sections.keys()) == list(range(1, 16))


def test_subsections_under_correct_parent():
    sections = page.parse_sections(page.strip_frontmatter(_SAMPLE))

    section_3_labels = [label for label, _ in sections[3].subsections]
    assert section_3_labels == ["3.1 What is a Trend?", "3.2 LTRP"]

    section_12_labels = [label for label, _ in sections[12].subsections]
    assert section_12_labels == ["12.1 Moving Averages", "12.2 RSI"]

    # A section without sub-sections must report an empty list, not borrow another
    # parent's children.
    assert sections[1].subsections == []


def test_frontmatter_stripped():
    stripped = page.strip_frontmatter(_SAMPLE)

    assert "version: v1.0" not in stripped
    assert "known_gaps" not in stripped
    assert stripped.lstrip().startswith("# methodology.md")


def test_paywall_disabled_by_default():
    assert page.PAYWALL_ENABLED is False
