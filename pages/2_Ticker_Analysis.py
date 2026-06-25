"""Streamlit page — Screen 2: Ticker Analysis.

Pick any active ticker and read its latest computed indicators (left) beside its
latest research brief (right). The indicators come from ``indicator_snapshots``
(written by scripts/analyze.py); the brief comes from the ``analyses`` table
(written by scripts/brief.py). If no brief exists yet, a button shells out to
scripts/brief.py to generate one on demand — this page never re-implements the
Groq call inline (analyzer/brief logic stays in its owning module).

RESEARCH SUPPORT ONLY. Indicator values and the descriptive brief are for manual
review — never buy/sell signals, predictions, or confidence scores (CLAUDE.md
governance constraints).

This page reads the DB read-only. The only write is delegated to scripts/brief.py
as a separate subprocess, which owns its own connection. No new dependencies:
streamlit is already pinned; brief.py is reused, not duplicated.

Run the app from the repo root:
    streamlit run app.py        # then pick "Ticker Analysis" in the sidebar
"""

import subprocess
import sqlite3
import sys
from pathlib import Path

import streamlit as st

# DB lives at <repo>/data/analyses.db regardless of CWD. This file sits in
# <repo>/pages/, so the DB is two parents up (mirrors 1_Daily_Screener.py).
REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "analyses.db"
BRIEF_SCRIPT = REPO_ROOT / "scripts" / "brief.py"

PAGE_TITLE = "NSE Ticker Analysis"
DISCLAIMER = "Research support only — candidates for manual review, **not trade signals**."
ROUND_DECIMALS = 2
EMPTY_CELL = "—"

# brief.py marks its rows only inside raw_json (the analyses table has no source
# column). Match on that marker so an older analyzer.py narrative is never shown
# in place of the brief. Keep the spacing identical to json.dumps default output.
BRIEF_SOURCE_MARKER = '"source": "brief.py"'

# CLAUDE.md / brief.py governance rule: the MACD signal line is shown as the
# "trigger line", never "signal".
TRIGGER_LINE_LABEL = "Trigger Line"

# Volume-ratio interpretation bands (today's volume vs its 20-day average).
VOL_RATIO_HIGH = 1.5  # >= this: "High conviction"
VOL_RATIO_AVG = 1.0  # >= this (and < HIGH): "Average"; below: "Below average"

# On-demand brief generation is a metered Groq call; cap how long we wait.
SUBPROCESS_TIMEOUT_SECONDS = 120


# ── Helpers ──────────────────────────────────────────────────────────────────


def _round2(value: float | None) -> float | None:
    """Round to ROUND_DECIMALS decimals; None passes through (mirrors analyze.py)."""
    return None if value is None else round(value, ROUND_DECIMALS)


def _fmt(value: float | None) -> str:
    """Render a stored numeric value for display; None becomes EMPTY_CELL."""
    rounded = _round2(value)
    return EMPTY_CELL if rounded is None else str(rounded)


# ── Data access (read-only) ────────────────────────────────────────────────


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-only so the UI can never contend with the writers."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """True if a table is present — guard so a half-built DB shows guidance."""
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def active_tickers(conn: sqlite3.Connection) -> list[str]:
    """All active instruments, alphabetical (the Nifty 500 universe)."""
    rows = conn.execute(
        "SELECT ticker FROM instruments WHERE is_active = 1 ORDER BY ticker"
    ).fetchall()
    return [r["ticker"] for r in rows]


def latest_snapshot(conn: sqlite3.Connection, ticker: str) -> sqlite3.Row | None:
    """Most recent indicator_snapshots row for ticker, or None."""
    return conn.execute(
        """
        SELECT * FROM indicator_snapshots
        WHERE ticker = ?
        ORDER BY analysis_date DESC
        LIMIT 1
        """,
        (ticker,),
    ).fetchone()


def latest_brief(conn: sqlite3.Connection, ticker: str) -> sqlite3.Row | None:
    """Most recent brief.py-sourced analyses row for ticker, or None.

    Filtered on the raw_json source marker so an older analyzer.py narrative for
    the same ticker is never mistaken for the brief.
    """
    return conn.execute(
        """
        SELECT analysis_date, governance_overall, narrative, created_at
        FROM analyses
        WHERE ticker = ? AND raw_json LIKE ?
        ORDER BY analysis_date DESC, created_at DESC
        LIMIT 1
        """,
        (ticker, f"%{BRIEF_SOURCE_MARKER}%"),
    ).fetchone()


# ── On-demand generation (delegate to scripts/brief.py) ─────────────────────


def generate_brief(symbol: str, snapshot_date: str) -> tuple[bool, str]:
    """Shell out to scripts/brief.py for one ticker. Returns (ok, message).

    Passes --date={snapshot_date} so brief.py's manual-mode snapshot lookup (which
    otherwise defaults to today) matches the snapshot we're displaying, and the
    saved brief gets that same analysis_date. Uses sys.executable so the brief
    runs under the same interpreter as the app. Never raises — failures surface
    to the UI with brief.py's own stderr.
    """
    try:
        result = subprocess.run(
            [sys.executable, str(BRIEF_SCRIPT), "--ticker", symbol, "--date", snapshot_date],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return False, f"brief.py timed out after {SUBPROCESS_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001 — report, never crash the page
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "brief.py exited non-zero").strip()
    return True, (result.stdout or "Brief generated.").strip()


# ── Rendering ────────────────────────────────────────────────────────────────


def _timeframe_block(col, label: str, lines: list[str]) -> None:
    """Render one timeframe's indicator lines under a bold sub-header."""
    col.markdown(f"**{label}**")
    col.markdown("\n".join(f"- {line}" for line in lines))


def _vol_interpretation(vol_ratio: float) -> str:
    """Map vol_ratio to its descriptive band (display only, not a signal)."""
    if vol_ratio >= VOL_RATIO_HIGH:
        return "High conviction"
    if vol_ratio >= VOL_RATIO_AVG:
        return "Average"
    return "Below average"


def render_volume(col, snap: sqlite3.Row) -> None:
    """Render the daily-volume section. Caption-only when no volume is stored."""
    vol_daily = snap["vol_daily"]
    if vol_daily is None:
        col.caption("Volume data not available")
        return

    vol_sma_20 = snap["vol_sma_20"]
    vol_ratio = snap["vol_ratio"]
    lines = [f"Volume: {vol_daily:,}"]
    if vol_sma_20 is not None:
        lines.append(f"Avg Volume (20d): {vol_sma_20:,.0f}")
    if vol_ratio is not None:
        lines.append(f"Vol Ratio: {vol_ratio} — {_vol_interpretation(vol_ratio)}")
    _timeframe_block(col, "Volume (Daily)", lines)


def render_indicators(col, snap: sqlite3.Row) -> None:
    """Lay out the latest snapshot by timeframe (Monthly → Weekly → Daily).

    Values are already 2-decimal-rounded on write; _round2 is applied again for a
    consistent display contract. MACD signal columns render as the trigger line.
    """
    col.subheader("Indicators")
    col.caption(
        f"Snapshot {snap['analysis_date']} · close {_fmt(snap['latest_close'])} "
        f"(as of {snap['latest_date']})"
    )

    _timeframe_block(
        col,
        "Monthly",
        [
            f"SMA20: {_fmt(snap['monthly_sma20'])}",
            f"RSI14: {_fmt(snap['monthly_rsi14'])}",
            f"MACD Line: {_fmt(snap['monthly_macd'])}",
            f"{TRIGGER_LINE_LABEL}: {_fmt(snap['monthly_macd_signal'])}",
            f"Histogram: {_fmt(snap['monthly_macd_hist'])}",
            f"Bollinger U / M / L: {_fmt(snap['monthly_bb_upper'])} / "
            f"{_fmt(snap['monthly_bb_mid'])} / {_fmt(snap['monthly_bb_lower'])}",
        ],
    )
    _timeframe_block(
        col,
        "Weekly",
        [
            f"SMA20 / SMA50: {_fmt(snap['weekly_sma20'])} / {_fmt(snap['weekly_sma50'])}",
            f"RSI14: {_fmt(snap['weekly_rsi14'])}",
            f"MACD Line: {_fmt(snap['weekly_macd'])}",
            f"{TRIGGER_LINE_LABEL}: {_fmt(snap['weekly_macd_signal'])}",
            f"Histogram: {_fmt(snap['weekly_macd_hist'])}",
            f"Bollinger U / M / L: {_fmt(snap['weekly_bb_upper'])} / "
            f"{_fmt(snap['weekly_bb_mid'])} / {_fmt(snap['weekly_bb_lower'])}",
        ],
    )
    _timeframe_block(
        col,
        "Daily",
        [
            f"SMA50 / SMA200: {_fmt(snap['daily_sma50'])} / {_fmt(snap['daily_sma200'])}",
            f"RSI14: {_fmt(snap['daily_rsi14'])}",
            f"MACD Line: {_fmt(snap['daily_macd'])}",
            f"{TRIGGER_LINE_LABEL}: {_fmt(snap['daily_macd_signal'])}",
            f"Histogram: {_fmt(snap['daily_macd_hist'])}",
            f"Bollinger U / M / L: {_fmt(snap['daily_bb_upper'])} / "
            f"{_fmt(snap['daily_bb_mid'])} / {_fmt(snap['daily_bb_lower'])}",
        ],
    )
    render_volume(col, snap)


def render_brief(col, ticker: str, brief: sqlite3.Row | None, snap: sqlite3.Row | None) -> None:
    """Render the latest brief, or a generate button when none exists."""
    col.subheader("Research brief")

    if brief is not None:
        col.caption(f"Brief {brief['analysis_date']}")
        if brief["governance_overall"] == "flagged":
            col.warning("⚠ Governance flag — see brief text below.")
        col.markdown(brief["narrative"] or EMPTY_CELL)
        return

    if snap is None:
        col.info("No brief yet, and no indicator snapshot to base one on.")
        return

    col.info("No brief yet for this ticker.")
    if col.button("Generate brief", key=f"gen_{ticker}"):
        with st.spinner(f"Generating brief for {ticker}…"):
            ok, message = generate_brief(ticker, snap["analysis_date"])
        if ok:
            st.rerun()
        else:
            col.error(f"Brief generation failed: {message}")


# ── UI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title(PAGE_TITLE)
    st.caption(DISCLAIMER)

    if not DB_PATH.exists():
        st.error(f"Database not found at {DB_PATH}. Run scripts/init_db.py first.")
        return

    conn = open_readonly(DB_PATH)
    try:
        for table in ("instruments", "indicator_snapshots", "analyses"):
            if not table_exists(conn, table):
                st.info(
                    f"`{table}` table not found. "
                    "Run `python scripts/init_db.py`, then screen.py / analyze.py / brief.py."
                )
                return

        tickers = active_tickers(conn)
        if not tickers:
            st.info("No active instruments. Seed the `instruments` table first.")
            return

        ticker = st.selectbox("Ticker", tickers, index=0)
        snap = latest_snapshot(conn, ticker)
        brief = latest_brief(conn, ticker)
    finally:
        conn.close()

    left, right = st.columns(2)
    if snap is None:
        left.subheader("Indicators")
        left.info("No indicator snapshot yet. Run `python scripts/analyze.py` for this ticker.")
    else:
        render_indicators(left, snap)
    render_brief(right, ticker, brief, snap)


if __name__ == "__main__":
    main()
