"""Streamlit page — Screen 4: Multi-Timeframe Indicator Screen (methodology §16).

Two levels over the ``indicator_snapshots`` / ``ohlcv_{daily,weekly,monthly}`` /
``support_resistance`` tables, built on top of scripts/indicator_screen.py's
derivation layer:

    Level 1 (Watchlist)      : one compact row per active ticker — ticker,
                                price, only its lit-up chips (tagged M/W/D).
                                Facts only, no verdict column. Tap a row to
                                open that ticker's diary.
    Level 2 (Timeframe diary): Monthly -> Weekly -> Daily, identical Style C
                                layout on each (every reading shown, notable
                                ones highlighted). An alignment strip pinned
                                at top reports *that* timeframes agree — never
                                what to do about it (methodology §16.1 rule 3).

GOVERNANCE (methodology §16.1 / indicator-screen-spec.md §1): every reading
shown is a computed fact. This page never decides trend direction, never sums
indicators into a verdict, and never emits buy/sell/size. Highlighting points
the eye; it does not judge. squeeze_reviews is a write-only journal here — the
live-squeeze render path (scripts/indicator_screen.squeeze_lit) never reads it
back, so past labels can never influence how a *new* squeeze is displayed
(rule 5).

RESEARCH SUPPORT ONLY. This page reads the DB read-only except for one
explicit write path (the squeeze-review journal, a separate short-lived
connection) — it never touches indicator_snapshots, ohlcv_*, or
support_resistance. scripts/analyze.py remains the sole writer of
indicator_snapshots; scripts/screen.py remains the sole writer of
scan_results. No new dependencies: streamlit and pandas are already pinned.

Run the app from the repo root:
    streamlit run app.py        # then pick "Indicator Screen" in the sidebar
"""

import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# DB lives at <repo>/data/analyses.db regardless of CWD. This file sits in
# <repo>/pages/, so the DB is two parents up (mirrors 1_Daily_Screener.py).
REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "analyses.db"

# scripts/ holds the derivation layer (indicator_screen.py) and its
# dependencies (analyze.py, screen.py) — make it importable, mirroring how
# tests/ import scripts/ modules.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import indicator_screen as ix  # noqa: E402

PAGE_TITLE = "NSE Indicator Screen"
DISCLAIMER = "Research support only — computed facts for manual review, **not trade signals**."
ROUND_DECIMALS = 2
EMPTY_CELL = "—"

# CLAUDE.md / brief.py governance rule: the MACD signal line is shown as the
# "trigger line", never "signal" — mirrors pages/2_Ticker_Analysis.py exactly.
TRIGGER_LINE_LABEL = "Trigger Line"

# Diary page order: Monthly -> Weekly -> Daily, the order a trader reads a
# chart (indicator-screen-spec.md §5) — deliberately NOT ix.TIMEFRAMES's order.
DIARY_ORDER = ("monthly", "weekly", "daily")
TF_LABEL = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}
TF_TAG = {"daily": "D", "weekly": "W", "monthly": "M"}

NOTHING_LIT = "Nothing lit up today"


# ── Formatting helpers (mirrors pages/1 and pages/2) ──────────────────────────


def _round2(value: float | None) -> float | None:
    return None if value is None else round(value, ROUND_DECIMALS)


def _fmt(value: float | None) -> str:
    rounded = _round2(value)
    return EMPTY_CELL if rounded is None else str(rounded)


# ── Data access (read-only) ────────────────────────────────────────────────


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-only so the UI can never contend with the writers."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def open_writable(db_path: Path) -> sqlite3.Connection:
    """A short-lived writable connection, used ONLY for the squeeze-review
    journal insert. Opened and closed per-write — never held for the page's
    lifetime, so the read-only connection above stays the primary access path.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def latest_snapshot_per_active_ticker(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """One row per active instrument: its most recent indicator_snapshots row."""
    return conn.execute(
        """
        SELECT s.* FROM indicator_snapshots s
        JOIN instruments i ON i.ticker = s.ticker AND i.is_active = 1
        WHERE s.analysis_date = (
            SELECT MAX(s2.analysis_date) FROM indicator_snapshots s2 WHERE s2.ticker = s.ticker
        )
        ORDER BY s.ticker
        """
    ).fetchall()


def snapshot_by_date(
    conn: sqlite3.Connection, ticker: str, analysis_date: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM indicator_snapshots WHERE ticker = ? AND analysis_date = ?",
        (ticker, analysis_date),
    ).fetchone()


def squeeze_reviews_for(conn: sqlite3.Connection, ticker: str, timeframe: str) -> list[sqlite3.Row]:
    """Past journal entries for one ticker/timeframe, most recent first.

    Read-only display of the trader's own past notes (methodology §16.1 rule 5,
    sanctioned use #1: "show that record back"). Never consulted by the
    live-squeeze computation — squeeze_lit() has no knowledge this table exists.
    """
    return conn.execute(
        """
        SELECT review_date, verdict, note, outcome FROM squeeze_reviews
        WHERE ticker = ? AND timeframe = ?
        ORDER BY review_date DESC
        """,
        (ticker, timeframe),
    ).fetchall()


def save_squeeze_review(
    db_path: Path, ticker: str, timeframe: str, verdict: str, note: str, outcome: str
) -> tuple[bool, str]:
    """Insert or overwrite today's journal entry for this ticker/timeframe.

    UNIQUE(ticker, timeframe, review_date) — a second save today overwrites,
    never duplicates. Never raises; the caller shows the message.
    """
    conn = open_writable(db_path)
    try:
        conn.execute(
            """
            INSERT INTO squeeze_reviews (ticker, timeframe, review_date, verdict, note, outcome)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, timeframe, review_date) DO UPDATE SET
                verdict = excluded.verdict, note = excluded.note, outcome = excluded.outcome
            """,
            (ticker, timeframe, date.today().isoformat(), verdict or None, note or None, outcome or None),
        )
        conn.commit()
        return True, "Saved."
    except Exception as exc:  # noqa: BLE001 — report, never crash the page
        return False, str(exc)
    finally:
        conn.close()


# ── Cached fact assembly (keyed on each ticker's own snapshot date) ──────────


@st.cache_data(show_spinner=False)
def cached_ticker_facts(db_path: str, ticker: str, analysis_date: str) -> ix.TickerFacts | None:
    """Facts for one ticker, cached on (ticker, analysis_date).

    A fresh scripts/analyze.py run gives a ticker a new analysis_date, which is
    a new cache key — the cache invalidates itself automatically the next time
    new data lands, with no manual cache-busting required.
    """
    conn = open_readonly(Path(db_path))
    try:
        snap = snapshot_by_date(conn, ticker, analysis_date)
        if snap is None:
            return None
        return ix.build_ticker_facts(conn, ticker, snap)
    finally:
        conn.close()


# ── Level 1 — Watchlist chips ──────────────────────────────────────────────


def _timeframe_chips(timeframe: str, tfacts: ix.TimeframeFacts) -> list[str]:
    """Every lit-up fact for one timeframe, tagged M/W/D (spec §5 example:
    "W: squeeze", "D: volume 2x")."""
    tag = TF_TAG[timeframe]
    chips = []
    if tfacts.rsi_lit and tfacts.rsi14 is not None:
        chips.append(f"{tag}: RSI {tfacts.rsi14:g}")
    if tfacts.macd_cross:
        chips.append(f"{tag}: MACD crossed {tfacts.macd_cross}")
    for (short, long), direction in tfacts.sma_pair_crosses.items():
        if direction:
            chips.append(f"{tag}: SMA {short}/{long} crossed {direction}")
    if tfacts.bb_lit:
        chips.append(f"{tag}: Bollinger {tfacts.bb_position} band touch")
    if tfacts.squeeze:
        chips.append(f"{tag}: squeeze (tightest in {ix.SQUEEZE_LOOKBACK[timeframe]})")
    if tfacts.sr_state:
        chips.append(f"{tag}: on {tfacts.sr_state}")
    return chips


def ticker_chips(facts: ix.TickerFacts) -> list[str]:
    """All lit-up chips across every timeframe, plus daily-only volume."""
    chips: list[str] = []
    for timeframe in ix.TIMEFRAMES:
        chips.extend(_timeframe_chips(timeframe, facts.timeframes[timeframe]))
    if facts.vol_lit:
        chips.append(f"D: volume {facts.vol_ratio:g}x ({facts.vol_lit})")
    return chips


def build_watchlist(conn: sqlite3.Connection, db_path: str) -> pd.DataFrame:
    """One row per active ticker with a snapshot. Sort: most-lit, then A-Z —
    rows with nothing lit sink to the bottom (spec §5)."""
    records = []
    for row in latest_snapshot_per_active_ticker(conn):
        facts = cached_ticker_facts(db_path, row["ticker"], row["analysis_date"])
        if facts is None:
            continue
        chips = ticker_chips(facts)
        records.append(
            {
                "Ticker": facts.ticker,
                "Price": _fmt(facts.latest_close),
                "Lit up": ", ".join(chips) if chips else NOTHING_LIT,
                "_chip_count": len(chips),
            }
        )
    df = pd.DataFrame.from_records(records)
    if df.empty:
        return df
    df = df.sort_values(by=["_chip_count", "Ticker"], ascending=[False, True])
    return df.drop(columns="_chip_count").reset_index(drop=True)


def render_watchlist(conn: sqlite3.Connection, db_path: str) -> None:
    df = build_watchlist(conn, db_path)
    if df.empty:
        st.info(
            "No indicator snapshots for active tickers yet. "
            "Run `python scripts/analyze.py` to populate the watchlist."
        )
        return

    st.write(f"**{len(df)} ticker(s)** with a snapshot")
    event = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="watchlist_table",
    )
    if event.selection.rows:
        selected = df.iloc[event.selection.rows[0]]["Ticker"]
        st.session_state["iscreen_ticker"] = selected
        st.session_state["iscreen_view"] = "diary"
        st.rerun()


# ── Level 2 — Timeframe diary ──────────────────────────────────────────────


def _alignment_facts(facts: ix.TickerFacts) -> list[str]:
    """Facts of AGREEMENT across all three timeframes only (methodology §16.1
    rule 3: reports *that* timeframes agree, never what to do about it).
    """
    out = []
    macd_by_tf = {tf: facts.timeframes[tf].macd_cross for tf in ix.TIMEFRAMES}
    fact = ix.agreement_fact("MACD crossed", macd_by_tf)
    if fact:
        out.append(fact)
    if all(facts.timeframes[tf].squeeze for tf in ix.TIMEFRAMES):
        out.append("Squeeze on all three timeframes")
    return out


def build_alignment_column_lines(tfacts: ix.TimeframeFacts) -> list[str]:
    """The small factual tag lines shown for one timeframe's alignment column."""
    return [
        f"MACD: {tfacts.macd_position or EMPTY_CELL}",
        f"RSI: {_fmt(tfacts.rsi14)}",
        f"S/R: {tfacts.sr_state or 'clear'}",
        f"Squeeze: {'yes' if tfacts.squeeze else 'no'}",
    ]


def render_alignment_strip(facts: ix.TickerFacts) -> None:
    """All three timeframes always visible as small factual tags, pinned above
    the selected timeframe's detail (spec §5) — so agreement is never hidden
    behind the segmented control.
    """
    st.markdown("**Alignment**")
    cols = st.columns(3)
    for col, timeframe in zip(cols, ix.TIMEFRAMES, strict=True):
        tfacts = facts.timeframes[timeframe]
        col.caption(TF_LABEL[timeframe])
        col.markdown("  \n".join(build_alignment_column_lines(tfacts)))

    for fact in _alignment_facts(facts):
        st.caption(f"• {fact}")


def _reading_line(label: str, value: str, lit: bool) -> str:
    """One Style C row. Lit readings are bolded — highlighting points the eye,
    it does not judge (methodology §16.1 rule 4); no color implies good/bad.
    """
    return f"- **{label}: {value}**" if lit else f"- {label}: {value}"


def build_timeframe_lines(timeframe: str, tfacts: ix.TimeframeFacts) -> list[str]:
    """Style C row text: every reading shown, notable ones highlighted.
    Identical row order on every page (spec §2 table order): MACD, RSI,
    Bollinger, MA pairs, Volume, Candle, S/R.
    """
    lines = []
    lines.append(
        _reading_line(
            "MACD",
            f"{TRIGGER_LINE_LABEL} position: {tfacts.macd_position or EMPTY_CELL}"
            + (f" (crossed {tfacts.macd_cross})" if tfacts.macd_cross else ""),
            bool(tfacts.macd_cross),
        )
    )
    lines.append(_reading_line("RSI(14)", _fmt(tfacts.rsi14), tfacts.rsi_lit))
    lines.append(
        _reading_line(
            "Bollinger",
            f"position {tfacts.bb_position or EMPTY_CELL}",
            tfacts.bb_lit,
        )
    )
    lines.append(
        _reading_line(
            "Squeeze",
            f"tightest in {ix.SQUEEZE_LOOKBACK[timeframe]}" if tfacts.squeeze else "not compressed",
            tfacts.squeeze,
        )
    )
    for pair in ix.SMA_PAIRS:
        position = tfacts.sma_pair_positions[pair]
        cross = tfacts.sma_pair_crosses[pair]
        detail = f"{position or EMPTY_CELL}" + (f" (crossed {cross})" if cross else "")
        lines.append(_reading_line(f"SMA {pair[0]}/{pair[1]}", detail, bool(cross)))
    lines.append(_reading_line("Candle", tfacts.candle or EMPTY_CELL, False))  # never lights up
    lines.append(_reading_line("S/R", tfacts.sr_state or "clear", tfacts.sr_state is not None))
    return lines


def render_timeframe_detail(timeframe: str, tfacts: ix.TimeframeFacts) -> None:
    st.markdown("\n".join(build_timeframe_lines(timeframe, tfacts)))


def build_volume_line(facts: ix.TickerFacts) -> str | None:
    """Volume is daily-only (methodology §9/§16.2 — no weekly/monthly ratio).
    None when volume data isn't available."""
    if facts.vol_ratio is None:
        return None
    lit = facts.vol_lit is not None
    return _reading_line("Vol ratio", f"{facts.vol_ratio:g}x ({facts.vol_lit or 'normal'})", lit)


def render_volume(facts: ix.TickerFacts) -> None:
    st.markdown("**Volume (Daily only)**")
    line = build_volume_line(facts)
    if line is None:
        st.caption("Volume data not available")
        return
    st.markdown(line)


def render_squeeze_review(db_path: Path, conn: sqlite3.Connection, ticker: str, timeframe: str) -> None:
    """Journal write path for a flagged squeeze. Never read by squeeze_lit() —
    purely the trader's own record (methodology §16.1 rule 5)."""
    with st.expander(f"Log this {TF_LABEL[timeframe]} squeeze"):
        with st.form(key=f"squeeze_review_{ticker}_{timeframe}"):
            verdict = st.selectbox("Verdict", ["", "real", "noise"], key=f"verdict_{ticker}_{timeframe}")
            note = st.text_area("Note", key=f"note_{ticker}_{timeframe}")
            outcome = st.text_input(
                "Outcome (fill in later)", key=f"outcome_{ticker}_{timeframe}"
            )
            if st.form_submit_button("Save review"):
                ok, message = save_squeeze_review(db_path, ticker, timeframe, verdict, note, outcome)
                if ok:
                    st.success(message)
                else:
                    st.error(message)

        past = squeeze_reviews_for(conn, ticker, timeframe)
        if past:
            st.caption("Past reviews (your own journal — never fed back into this flag)")
            st.dataframe(
                pd.DataFrame.from_records([dict(row) for row in past]),
                use_container_width=True,
                hide_index=True,
            )


def render_diary(conn: sqlite3.Connection, db_path: str, ticker: str) -> None:
    if st.button("← Back to Watchlist"):
        st.session_state["iscreen_view"] = "watchlist"
        st.rerun()

    row = conn.execute(
        "SELECT * FROM indicator_snapshots WHERE ticker = ? ORDER BY analysis_date DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if row is None:
        st.info(f"No indicator snapshot for {ticker}.")
        return

    facts = cached_ticker_facts(db_path, ticker, row["analysis_date"])
    if facts is None:
        st.info(f"No indicator snapshot for {ticker}.")
        return

    st.subheader(ticker)
    st.caption(f"Snapshot {facts.analysis_date} · close {_fmt(facts.latest_close)}")

    render_alignment_strip(facts)
    st.divider()

    default_label = TF_LABEL[st.session_state.get("iscreen_tf", "monthly")]
    selected_label = st.segmented_control(
        "Timeframe",
        [TF_LABEL[tf] for tf in DIARY_ORDER],
        default=default_label,
        key="iscreen_tf_control",
    )
    selected_tf = (
        next(tf for tf in DIARY_ORDER if TF_LABEL[tf] == selected_label) if selected_label else "monthly"
    )
    st.session_state["iscreen_tf"] = selected_tf

    render_timeframe_detail(selected_tf, facts.timeframes[selected_tf])
    if selected_tf == "daily":
        render_volume(facts)

    if facts.timeframes[selected_tf].squeeze:
        render_squeeze_review(Path(db_path), conn, ticker, selected_tf)


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
        for table in ("instruments", "indicator_snapshots", "support_resistance", "squeeze_reviews"):
            if not table_exists(conn, table):
                st.info(
                    f"`{table}` table not found. "
                    "Run `python scripts/init_db.py`, then screen.py / analyze.py."
                )
                return

        view = st.session_state.get("iscreen_view", "watchlist")
        if view == "diary" and st.session_state.get("iscreen_ticker"):
            render_diary(conn, str(DB_PATH), st.session_state["iscreen_ticker"])
        else:
            render_watchlist(conn, str(DB_PATH))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
