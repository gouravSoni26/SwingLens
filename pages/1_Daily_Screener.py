"""Streamlit page — Screen 1: Daily Screener.

Read-only view over the ``scan_results`` table (candidates surfaced by
scripts/screen.py). Pick a scan date, optionally filter by ticker, and read the
candidate list as a clean table. Auto-listed in the sidebar nav by Streamlit's
native multipage layout — app.py and all existing files stay untouched.

RESEARCH SUPPORT ONLY. Every row here already passed all three screening rules
(see scripts/screen.py) — these are candidates for manual review, never buy/sell
signals, predictions, or confidence scores (CLAUDE.md governance constraints).

This page is UI only. It opens the DB read-only and never writes — screen.py
remains the sole writer of scan_results. No new dependencies: streamlit and
pandas are already pinned in requirements.txt.

Run the app from the repo root:
    streamlit run app.py        # then pick "Daily Screener" in the sidebar
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# DB lives at <repo>/data/analyses.db regardless of CWD. This file sits in
# <repo>/pages/, so the DB is two parents up (mirrors screen.py's resolution).
REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "analyses.db"

# db_sync.py lives at repo root — make it importable (Streamlit multipage does
# NOT re-run app.py's top-level code on direct page navigation, so each page
# needs its own cold-start DB fetch call).
sys.path.insert(0, str(REPO_ROOT))
from db_sync import ensure_db_present  # noqa: E402

PAGE_TITLE = "NSE Daily Screener"
DISCLAIMER = "Research support only — candidates for manual review, **not trade signals**."
ROUND_DECIMALS = 2

# breakout_kind ('up' | 'down') is the only "setup" stored; render it readable.
BREAKOUT_LABELS = {"up": "Up breakout", "down": "Down breakout"}
EMPTY_CELL = "—"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _round2(value: float | None) -> float | None:
    """Round to ROUND_DECIMALS decimals; None passes through (mirrors analyze.py)."""
    return None if value is None else round(value, ROUND_DECIMALS)


def _normalize_ticker(raw: str) -> str:
    """Input-boundary normalization so 'reliance' matches stored 'RELIANCE.NS'."""
    return raw.strip().upper()


def _setup_label(breakout_kind: str | None) -> str:
    """'up'/'down' -> readable setup type; EMPTY_CELL when unknown/missing."""
    return BREAKOUT_LABELS.get(breakout_kind or "", EMPTY_CELL)


def _sr_label(level: float | None, kind: str | None) -> str:
    """Render the nearest S/R level as 'price (kind)', e.g. '1234.5 (resistance)'."""
    if level is None:
        return EMPTY_CELL
    price = _round2(level)
    return f"{price} ({kind})" if kind else f"{price}"


# Intentionally separate from screen.py's rule_sma_trend(): that is the filter
# GATE deciding candidacy; this only LABELS already-passed rows for display. The
# overlap is by design — do not refactor into a shared helper.
def _trend_label(
    daily_short: float | None,
    daily_long: float | None,
    weekly_short: float | None,
    weekly_long: float | None,
) -> str:
    """Describe SMA alignment. Candidates passed Rule 3, so this is bullish by
    construction — shown for transparency, NOT recomputed as a verdict."""
    values = (daily_short, daily_long, weekly_short, weekly_long)
    if any(v is None for v in values):
        return EMPTY_CELL
    daily_up = daily_short > daily_long
    weekly_up = weekly_short > weekly_long
    if daily_up and weekly_up:
        return "Bullish (daily + weekly)"
    if daily_up:
        return "Bullish (daily)"
    if weekly_up:
        return "Bullish (weekly)"
    return "Mixed"


# ── Data access (read-only) ────────────────────────────────────────────────


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-only so the UI can never contend with screen.py."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def scan_results_exists(conn: sqlite3.Connection) -> bool:
    """True if the scan_results table is present (created by scripts/init_db.py).

    The DB file can exist (created by storage.init_db for the analyses table)
    without scan_results — guard so we show guidance, not a raw traceback.
    """
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scan_results'"
        ).fetchone()
        is not None
    )


def available_scan_dates(conn: sqlite3.Connection) -> list[str]:
    """Distinct scan dates that have candidates, newest first."""
    rows = conn.execute(
        "SELECT DISTINCT scan_date FROM scan_results ORDER BY scan_date DESC"
    ).fetchall()
    return [r["scan_date"] for r in rows]


def load_scan(conn: sqlite3.Connection, scan_date: str) -> pd.DataFrame:
    """Build the display table for one scan date. Empty frame if none."""
    rows = conn.execute(
        """
        SELECT ticker, latest_close, breakout_kind, nearest_level, nearest_level_kind,
               daily_sma50, daily_sma200, weekly_sma20, weekly_sma50
        FROM scan_results
        WHERE scan_date = ?
        ORDER BY ticker ASC
        """,
        (scan_date,),
    ).fetchall()
    records = [
        {
            "Ticker": r["ticker"],
            "Setup type": _setup_label(r["breakout_kind"]),
            "S/R level": _sr_label(r["nearest_level"], r["nearest_level_kind"]),
            "Trend alignment": _trend_label(
                r["daily_sma50"], r["daily_sma200"], r["weekly_sma20"], r["weekly_sma50"]
            ),
            "Close": _round2(r["latest_close"]),
        }
        for r in rows
    ]
    return pd.DataFrame.from_records(records)


# ── UI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title(PAGE_TITLE)
    st.caption(DISCLAIMER)

    ensure_db_present()  # cold-start only — no-op if data/analyses.db already exists

    if not DB_PATH.exists():
        st.error(f"Database not found at {DB_PATH}. Run scripts/init_db.py first.")
        return

    conn = open_readonly(DB_PATH)
    try:
        if not scan_results_exists(conn):
            st.info(
                "scan_results table not found. "
                "Run `python scripts/init_db.py` then `python scripts/screen.py`."
            )
            return
        dates = available_scan_dates(conn)
        if not dates:
            st.info("No scan results yet. Run `python scripts/screen.py` to populate candidates.")
            return

        scan_date = st.selectbox("Scan date", dates, index=0)
        ticker_filter = _normalize_ticker(st.text_input("Filter by ticker (optional)"))
        df = load_scan(conn, scan_date)
    finally:
        conn.close()

    if ticker_filter:
        df = df[df["Ticker"].str.contains(ticker_filter, regex=False)]

    if df.empty:
        suffix = f" matching '{ticker_filter}'." if ticker_filter else "."
        st.info(f"No candidates for {scan_date}{suffix}")
        return

    st.write(f"**{len(df)} candidate(s)** on {scan_date}")
    st.dataframe(df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
