"""Tests for pages/2_Ticker_Analysis.py data-access helpers.

The two queries that can silently show the wrong thing are latest_snapshot
(must pick the newest snapshot) and latest_brief (must pick the brief.py-sourced
row, not an older analyzer.py narrative for the same ticker). Both are exercised
against an in-memory SQLite seeded with the columns the helpers read.

streamlit is imported by the page module at top level; if it is not installed in
the test environment the whole module is skipped (these tests cover pure SQL, not
the UI). Run from the repo root:
    trading-app/Scripts/python.exe -m pytest tests/test_ticker_analysis.py
"""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("streamlit")  # page module imports streamlit at top level

# Load the page module by path (filename starts with a digit, so it is not a
# normal import name).
_MODULE_PATH = Path(__file__).resolve().parent.parent / "pages" / "2_Ticker_Analysis.py"
_spec = importlib.util.spec_from_file_location("ticker_analysis_page", _MODULE_PATH)
page = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(page)


def _seed_db() -> sqlite3.Connection:
    """In-memory DB with the columns the helpers read. Row factory matches prod."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE indicator_snapshots (
            ticker TEXT, analysis_date TEXT, latest_close REAL, latest_date TEXT
        );
        CREATE TABLE analyses (
            ticker TEXT, analysis_date TEXT, governance_overall TEXT,
            narrative TEXT, raw_json TEXT, created_at TEXT
        );
        """
    )
    return conn


def test_latest_snapshot_returns_newest():
    conn = _seed_db()
    conn.executemany(
        "INSERT INTO indicator_snapshots (ticker, analysis_date, latest_close, latest_date) "
        "VALUES (?, ?, ?, ?)",
        [
            ("RELIANCE.NS", "2026-06-17", 100.0, "2026-06-17"),
            ("RELIANCE.NS", "2026-06-19", 101.0, "2026-06-19"),  # newest
            ("TCS.NS", "2026-06-19", 50.0, "2026-06-19"),
        ],
    )

    snap = page.latest_snapshot(conn, "RELIANCE.NS")

    assert snap is not None
    assert snap["analysis_date"] == "2026-06-19"
    assert snap["latest_close"] == 101.0


def test_latest_brief_prefers_brief_py_over_newer_analyzer_row():
    conn = _seed_db()
    conn.executemany(
        "INSERT INTO analyses (ticker, analysis_date, governance_overall, narrative, "
        "raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [
            # brief.py row (older date) — the one we MUST surface.
            (
                "RELIANCE.NS",
                "2026-06-18",
                "clean",
                "BRIEF narrative",
                json.dumps({"source": "brief.py", "brief": "BRIEF narrative"}),
                "2026-06-18 09:00:00",
            ),
            # analyzer.py row (newer date) — must be ignored, no source marker.
            (
                "RELIANCE.NS",
                "2026-06-20",
                "clean",
                "ANALYZER narrative",
                json.dumps({"timeframes": {}}),
                "2026-06-20 09:00:00",
            ),
        ],
    )

    brief = page.latest_brief(conn, "RELIANCE.NS")

    assert brief is not None
    assert brief["narrative"] == "BRIEF narrative"
    assert brief["analysis_date"] == "2026-06-18"


def test_latest_brief_returns_none_when_only_analyzer_rows():
    conn = _seed_db()
    conn.execute(
        "INSERT INTO analyses (ticker, analysis_date, governance_overall, narrative, "
        "raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "TCS.NS",
            "2026-06-20",
            "clean",
            "ANALYZER only",
            json.dumps({"timeframes": {}}),
            "2026-06-20 09:00:00",
        ),
    )

    assert page.latest_brief(conn, "TCS.NS") is None
