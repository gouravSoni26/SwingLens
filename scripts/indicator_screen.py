# AI role: research support only — never generates trade signals, predictions, or confidence scores
"""Multi-Timeframe Indicator Screen — derivation layer (methodology.md §16).

Named constants + pure derivation functions for the SwingLens Indicator Screen
(pages/4_Indicator_Screen.py). Nothing here infers trend direction, sums
indicators into a verdict, or emits a buy/sell/size instruction — every
function returns a plain factual token (a number, or a yes/no a machine
derives exactly), per methodology §16.1.

Store the number, derive the flag (§16.3): ``indicator_snapshots`` stores raw
SMA readings (scripts/analyze.py); everything "lit up" here is computed at
render time from those raw readings plus the constants below. Tuning a
threshold is a config edit to this file, never a data migration.

Crosses (MACD sign-flip, SMA-pair ordering flip) and the squeeze ("tightest in
N", §12.4 Play 3) are both derived from the SAME source — the last
``MAX_ROWS`` rows of ``ohlcv_{daily,weekly,monthly}`` — rather than from
``indicator_snapshots`` history. ``indicator_snapshots`` is sparse (one row per
``analyze.py`` run, not guaranteed to land once per trading day), so comparing
"this snapshot vs the previous snapshot" could silently skip periods or
compare non-adjacent ones. Reading straight from ``ohlcv_{tf}`` and dropping
the latest row always yields the true previous period for that timeframe,
matching methodology §16.4's same-timeframe rule (a weekly squeeze compares
prior weeks, never prior daily snapshots).

Reuses scripts/analyze.py's hand-rolled sma()/macd()/bollinger() (no
duplicated indicator math) and scripts/screen.py's Level/level_distance_pct
(no duplicated S/R zone-distance geometry) — this module only adds the
lit-up thresholds and comparison logic on top.
"""

import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze  # noqa: E402
import screen  # noqa: E402

# ── §16.3 Named constants (single source of truth) ────────────────────────────

RSI_LOW = 30
RSI_HIGH = 70  # 30/70 = starting reference (§12.2); empirical calibration deferred (§16.6)

VOL_NOTABLE = 2.0  # x of 20-day average volume
VOL_STRONG = 5.0
VOL_AVG_WINDOW = 20  # days

# Methodology-taught S/R proximity (§16.3, §4.3) — 5%, Saif-taught.
# Deliberately a DIFFERENT constant from screen.SR_PROXIMITY_PCT (2%), which is
# the OPERATIONAL screening-gate threshold that decides scan_results candidacy.
# methodology.md §16.5 records this as a confirmed, open divergence — reconciling
# screen.py's 2% is its own separate task. This screen displays the taught 5%
# value and never changes screen.py's gate.
DIARY_SR_PROXIMITY_PCT = 5.0

BB_PERIOD = analyze.BB_PERIOD  # methodology §12.4 — single source with analyze.py

SQUEEZE_LOOKBACK_DAILY = 20  # instinct dial — tuned by feel, not taught
SQUEEZE_LOOKBACK_WEEKLY = 20  # instinct dial
SQUEEZE_LOOKBACK_MONTHLY = 20  # instinct dial
SQUEEZE_LOOKBACK = {
    "daily": SQUEEZE_LOOKBACK_DAILY,
    "weekly": SQUEEZE_LOOKBACK_WEEKLY,
    "monthly": SQUEEZE_LOOKBACK_MONTHLY,
}

BREACH_BASIS = "close"  # wicks never count — restates the global rule (§1)

# SMA periods computed and stored per timeframe (which periods exist as
# columns) are owned by analyze.py (the producer) — reference analyze.SMA_PERIODS
# rather than redefining it here. This module only adds which PAIRS of those
# periods get watched for a crossover "lit up" (§16.2).
SMA_PAIRS = ((20, 50), (50, 100), (50, 200), (98, 100), (198, 200))

TIMEFRAMES = ("daily", "weekly", "monthly")
OHLCV_TABLE = {"daily": "ohlcv_daily", "weekly": "ohlcv_weekly", "monthly": "ohlcv_monthly"}

MAX_ROWS = analyze.MAX_ROWS  # same history window as analyze.py — one source


# ── Data access (read-only; mirrors analyze.py's helpers) ────────────────────


def load_closes(conn, timeframe: str, ticker: str) -> pd.Series:
    """Date-ordered close series for one ticker/timeframe (last MAX_ROWS rows)."""
    table = OHLCV_TABLE[timeframe]
    df = analyze.load_closes(conn, table, ticker)
    return analyze._tail_closes(df)


def load_latest_open(conn: sqlite3.Connection, timeframe: str, ticker: str) -> float | None:
    """The most recent candle's open for one ticker/timeframe, or None."""
    table = OHLCV_TABLE[timeframe]
    row = conn.execute(
        f"SELECT open FROM {table} WHERE ticker = ? ORDER BY date DESC LIMIT 1", (ticker,)
    ).fetchone()
    return float(row[0]) if row else None


def candle_color(open_: float | None, close: float | None) -> str | None:
    """'green' | 'red' | None — the latest candle's color. Context only — never
    lights up (methodology §16.2 / spec §2: "Candle — never — context only").
    """
    if open_ is None or close is None:
        return None
    return "green" if close >= open_ else "red"


# ── Crosses (derived — no stored "cross" column, methodology §16.4) ──────────


def macd_cross(closes: pd.Series) -> str | None:
    """'up' | 'down' | None — MACD line crossing its signal line vs the prior
    period, recomputed from the same close series as the current MACD (§12.3,
    §16.2). None when there is no prior period to compare or no crossover
    occurred.
    """
    if len(closes) < 2:
        return None
    curr_macd, curr_sig, _ = analyze.macd(closes)
    prev_macd, prev_sig, _ = analyze.macd(closes.iloc[:-1])
    if None in (curr_macd, curr_sig, prev_macd, prev_sig):
        return None
    if prev_macd <= prev_sig and curr_macd > curr_sig:
        return "up"
    if prev_macd >= prev_sig and curr_macd < curr_sig:
        return "down"
    return None


def sma_pair_cross(closes: pd.Series, short: int, long: int) -> str | None:
    """'up' | 'down' | None — the (short, long) SMA pair's ordering flip vs the
    prior period (§12.1, §16.2). None when insufficient history or no flip.
    """
    if len(closes) < long + 1:
        return None
    curr_short, curr_long = analyze.sma(closes, short), analyze.sma(closes, long)
    prev = closes.iloc[:-1]
    prev_short, prev_long = analyze.sma(prev, short), analyze.sma(prev, long)
    if None in (curr_short, curr_long, prev_short, prev_long):
        return None
    if prev_short <= prev_long and curr_short > curr_long:
        return "up"
    if prev_short >= prev_long and curr_short < curr_long:
        return "down"
    return None


# ── Squeeze (derived — "tightest in N", same-timeframe only, §16.4) ──────────


def _bb_width_series(closes: pd.Series, period: int = BB_PERIOD) -> pd.Series:
    """Rolling Bollinger band width (upper - lower) across the whole series.

    upper - lower == 2 * BB_STD * rolling_std; the SMA midpoint cancels out.
    """
    std = closes.rolling(period).std()
    return 2 * analyze.BB_STD * std


def squeeze_lit(closes: pd.Series, lookback: int) -> bool:
    """True if the current band width is the minimum over the last `lookback`
    periods of band-width history (methodology §12.4 Play 3, §16.2). False when
    there isn't enough width history to compare, or the current width isn't
    the minimum.
    """
    widths = _bb_width_series(closes).dropna()
    if len(widths) < lookback:
        return False
    window = widths.tail(lookback)
    return bool(window.iloc[-1] == window.min())


# ── Simple lit-up predicates (§16.2 / §16.3) ──────────────────────────────────


def rsi_lit(value: float | None) -> bool:
    """RSI lights up outside [RSI_LOW, RSI_HIGH] (§12.2, §16.2)."""
    return value is not None and (value < RSI_LOW or value > RSI_HIGH)


def bb_position(close: float | None, upper: float | None, lower: float | None) -> str | None:
    """'upper' | 'lower' | 'middle' | None — the always-shown Bollinger position
    fact (§12.4). None only when an input is missing. Lit-up is a narrower
    question ("touching either band") — see bb_lit().
    """
    if None in (close, upper, lower):
        return None
    if close >= upper:
        return "upper"
    if close <= lower:
        return "lower"
    return "middle"


def bb_lit(position: str | None) -> bool:
    """Lights up when the close touches or crosses either band (§12.4)."""
    return position in ("upper", "lower")


def macd_position(macd_line: float | None, macd_signal: float | None) -> str | None:
    """'above' | 'below' | None — MACD line vs its trigger line, right now
    (§12.3). Always-shown fact; macd_cross() is the lit-up transition on top
    of this, computed separately from ohlcv history.
    """
    if macd_line is None or macd_signal is None:
        return None
    return "above" if macd_line > macd_signal else "below"


def sma_pair_position(short_value: float | None, long_value: float | None) -> str | None:
    """'above' | 'below' | None — is the short SMA above or below the long SMA,
    right now (§12.1). Always-shown fact; sma_pair_cross() is the lit-up
    transition on top of this, computed separately from ohlcv history.
    """
    if short_value is None or long_value is None:
        return None
    return "above" if short_value > long_value else "below"


def vol_lit(vol_ratio: float | None) -> str | None:
    """'strong' | 'notable' | None per VOL_STRONG / VOL_NOTABLE thresholds (§9)."""
    if vol_ratio is None:
        return None
    if vol_ratio >= VOL_STRONG:
        return "strong"
    if vol_ratio >= VOL_NOTABLE:
        return "notable"
    return None


def sr_state(close: float | None, levels: list[screen.Level]) -> str | None:
    """'support' | 'resistance' | None — close within DIARY_SR_PROXIMITY_PCT of
    a human-drawn support_resistance zone (§4, §16.2). Reuses screen.py's zone
    geometry (screen.level_distance_pct); only the threshold differs.
    """
    if close is None or not levels:
        return None
    nearest = min(levels, key=lambda lv: screen.level_distance_pct(close, lv))
    if screen.level_distance_pct(close, nearest) <= DIARY_SR_PROXIMITY_PCT:
        return nearest.kind
    return None


# ── Alignment (fact of agreement only — never a verdict, §16.1 rule 3) ───────


def agreement_fact(label: str, values_by_timeframe: dict[str, str | None]) -> str | None:
    """A plain factual sentence when all timeframes report the SAME non-None
    value, e.g. "MACD crossed up on all three timeframes". None when
    timeframes disagree or any value is missing. This reports only *that*
    timeframes agree — it never concludes what to do about it (§16.1 rule 3).
    """
    values = list(values_by_timeframe.values())
    if not values or any(v is None for v in values):
        return None
    first = values[0]
    if all(v == first for v in values):
        return f"{label} {first} on all three timeframes"
    return None


# ── Fact assembly (one ticker, one timeframe / all three timeframes) ─────────


@dataclass(frozen=True, slots=True)
class TimeframeFacts:
    """One timeframe's computed facts for one ticker (methodology §16.2).

    ``*_position``/``rsi14``/``bb_position`` are always-shown facts (Style C:
    "every reading shown"). ``*_lit`` / ``*_cross`` / ``squeeze`` are the
    narrower "lit up" facts drawn from the same readings plus §16.3 thresholds.
    """

    timeframe: str
    close: float | None
    rsi14: float | None
    rsi_lit: bool
    macd_position: str | None
    macd_cross: str | None
    sma_pair_positions: dict[tuple[int, int], str | None]
    sma_pair_crosses: dict[tuple[int, int], str | None]
    bb_position: str | None
    bb_lit: bool
    squeeze: bool
    sr_state: str | None
    candle: str | None


@dataclass(frozen=True, slots=True)
class TickerFacts:
    """All three timeframes' facts for one ticker, plus daily-only volume."""

    ticker: str
    analysis_date: str
    latest_close: float | None
    timeframes: dict[str, TimeframeFacts] = field(default_factory=dict)
    vol_ratio: float | None = None
    vol_lit: str | None = None


def build_timeframe_facts(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: str,
    snap: sqlite3.Row,
    levels: list[screen.Level],
) -> TimeframeFacts:
    """Assemble one timeframe's facts. Position/value facts read the stored
    snapshot (already computed by analyze.py); cross/squeeze facts recompute
    from ohlcv_{timeframe} history, which the snapshot does not retain.
    """
    closes = load_closes(conn, timeframe, ticker)
    close = float(closes.iloc[-1]) if len(closes) else None
    latest_open = load_latest_open(conn, timeframe, ticker)

    rsi14 = snap[f"{timeframe}_rsi14"]
    macd_line = snap[f"{timeframe}_macd"]
    macd_signal = snap[f"{timeframe}_macd_signal"]
    bb_upper = snap[f"{timeframe}_bb_upper"]
    bb_lower = snap[f"{timeframe}_bb_lower"]
    position = bb_position(close, bb_upper, bb_lower)

    sma_pair_positions = {
        pair: sma_pair_position(snap[f"{timeframe}_sma{pair[0]}"], snap[f"{timeframe}_sma{pair[1]}"])
        for pair in SMA_PAIRS
    }
    sma_pair_crosses = {
        pair: (sma_pair_cross(closes, *pair) if len(closes) else None) for pair in SMA_PAIRS
    }

    return TimeframeFacts(
        timeframe=timeframe,
        close=close,
        rsi14=rsi14,
        rsi_lit=rsi_lit(rsi14),
        macd_position=macd_position(macd_line, macd_signal),
        macd_cross=macd_cross(closes) if len(closes) else None,
        sma_pair_positions=sma_pair_positions,
        sma_pair_crosses=sma_pair_crosses,
        bb_position=position,
        bb_lit=bb_lit(position),
        squeeze=squeeze_lit(closes, SQUEEZE_LOOKBACK[timeframe]) if len(closes) else False,
        sr_state=sr_state(close, levels),
        candle=candle_color(latest_open, close),
    )


def build_ticker_facts(conn: sqlite3.Connection, ticker: str, snap: sqlite3.Row) -> TickerFacts:
    """Assemble every timeframe's facts for one ticker from its latest snapshot."""
    levels = screen.load_sr_levels(conn, ticker)
    timeframes = {
        tf: build_timeframe_facts(conn, ticker, tf, snap, levels) for tf in TIMEFRAMES
    }
    return TickerFacts(
        ticker=ticker,
        analysis_date=snap["analysis_date"],
        latest_close=snap["latest_close"],
        timeframes=timeframes,
        vol_ratio=snap["vol_ratio"],
        vol_lit=vol_lit(snap["vol_ratio"]),
    )
