# AI role: research support only — never generates trade signals, predictions, or confidence scores
"""Per-ticker multi-timeframe indicator snapshot for the NSE Trading Analyst.

Computes a fixed set of hand-rolled technical indicators (SMA, RSI, MACD,
Bollinger Bands) on the Daily, Weekly and Monthly close series for a ticker,
persists the latest values to ``indicator_snapshots`` (SQLite first), then
writes a human-readable note to the Obsidian vault (best-effort secondary sink).

Two modes, identical analysis logic:

    Default (no args) : analyze every ticker in today's ``scan_results``
                        (scan_date = today). Zero candidates => clean exit 0.
    Manual (--ticker) : analyze one ticker directly off ``ohlcv_daily``,
                        bypassing ``scan_results`` entirely.

Indicators are hand-rolled in pandas (``.rolling`` / ``.ewm``) — no external
indicator library — consistent with scripts/screen.py. They are computed on the
last 300 rows per timeframe, which is sufficient for every period below.

Parameter provenance
--------------------
- RSI period 14         : methodology.md §12.2 ("vs prior 14 periods", "RSI(14)").
- MACD signal 9         : methodology.md §12.3 fixes the signal at a 9-period EMA.
- MACD fast/slow 12/26  : industry-standard defaults — §12.3 does NOT fix these
                          numerically, so the conventional 12/26 are used.
- Bollinger 20 / 2sd    : methodology.md §12.4 (20-period SMA, 2 standard devs).
- SMA pairs / RSI levels: per-instrument EMPIRICAL (methodology.md §15.2, §15.3).
                          Their calibration flags default to 0 and are NEVER set
                          to 1 here — calibration is a future manual step.

RESEARCH SUPPORT ONLY. This script reports raw indicator values for manual
review. It never emits buy/sell signals, predictions, confidence scores, or
order suggestions (CLAUDE.md governance constraints).

Schema source of truth: docs/phase3-schema.md + scripts/init_db.py
Usage:
    python scripts/analyze.py                      # today's scan candidates
    python scripts/analyze.py --ticker RELIANCE.NS # analyze one ticker directly
    python scripts/analyze.py --ticker X --no-obsidian   # skip the Obsidian write
"""

import argparse
import os
import sqlite3
import ssl
import sys
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Load .env so OBSIDIAN_API_KEY (and OBSIDIAN_HOST) are available when this
# script runs standalone, e.g. from Task Scheduler. Mirrors screen.py/app.py.
load_dotenv()

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "analyses.db"

# ── Indicator parameters (see "Parameter provenance" in the module docstring) ──
MAX_ROWS = 300  # rows of history per timeframe — enough for every period below
RSI_PERIOD = 14
MACD_FAST = 12  # industry-standard fast EMA span (§12.3 fixes only the signal)
MACD_SLOW = 26  # industry-standard slow EMA span
MACD_SIGNAL = 9  # methodology §12.3
BB_PERIOD = 20  # methodology §12.4
BB_STD = 2.0  # methodology §12.4

# SMA periods per timeframe (mirrors screen.py's named-constant pattern; long >=
# 2x short per methodology §12.1). Monthly uses a single SMA (no 50/200).
DAILY_SMA_SHORT = 50
DAILY_SMA_LONG = 200
WEEKLY_SMA_SHORT = 20
WEEKLY_SMA_LONG = 50
MONTHLY_SMA = 20

VOL_SMA_PERIOD = 20  # 20-day average volume — vol_ratio baseline

OBSIDIAN_VAULT_FOLDER = "05-Watchlist"

# Column order for indicator_snapshots writes. ticker + analysis_date form the
# conflict key; the rest are updated on re-run (UPSERT).
SNAPSHOT_COLUMNS = [
    "ticker",
    "analysis_date",
    "latest_close",
    "latest_date",
    "daily_sma50",
    "daily_sma200",
    "daily_rsi14",
    "daily_macd",
    "daily_macd_signal",
    "daily_macd_hist",
    "daily_bb_upper",
    "daily_bb_mid",
    "daily_bb_lower",
    "weekly_sma20",
    "weekly_sma50",
    "weekly_rsi14",
    "weekly_macd",
    "weekly_macd_signal",
    "weekly_macd_hist",
    "weekly_bb_upper",
    "weekly_bb_mid",
    "weekly_bb_lower",
    "monthly_sma20",
    "monthly_rsi14",
    "monthly_macd",
    "monthly_macd_signal",
    "monthly_macd_hist",
    "monthly_bb_upper",
    "monthly_bb_mid",
    "monthly_bb_lower",
    "vol_daily",
    "vol_sma_20",
    "vol_ratio",
    "sma_pair_calibrated",
    "rsi_calibrated",
]


# ── Hand-rolled indicators (pure; return the latest scalar value) ─────────────


def _last(series: pd.Series) -> float | None:
    """Latest value of a series as a float, or None if empty/NaN."""
    if len(series) == 0:
        return None
    value = series.iloc[-1]
    return None if pd.isna(value) else float(value)


def _round2(value: float | None) -> float | None:
    """Round to 2 decimals; None passes through. Single source for DB + note."""
    return None if value is None else round(value, 2)


def sma(closes: pd.Series, period: int) -> float | None:
    """Simple moving average — latest value (methodology §12.1 Role 1/2)."""
    return _last(closes.rolling(period).mean())


def rsi(closes: pd.Series, period: int = RSI_PERIOD) -> float | None:
    """Wilder's RSI — latest value, 0..100 (methodology §12.2).

    Wilder smoothing == an EMA with com = period - 1 and adjust=False.
    """
    delta = closes.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    avg_gain = gains.ewm(com=period - 1, adjust=False).mean()
    avg_loss = losses.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss
    return _last(100 - 100 / (1 + rs))


def macd(
    closes: pd.Series,
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> tuple[float | None, float | None, float | None]:
    """MACD line, signal line, histogram — latest values (methodology §12.3)."""
    fast_ema = closes.ewm(span=fast, adjust=False).mean()
    slow_ema = closes.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return _last(macd_line), _last(signal_line), _last(histogram)


def bollinger(
    closes: pd.Series, period: int = BB_PERIOD, mult: float = BB_STD
) -> tuple[float | None, float | None, float | None]:
    """Bollinger upper, mid (SMA), lower — latest values (methodology §12.4)."""
    bb_mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    bb_upper = bb_mid + mult * std
    bb_lower = bb_mid - mult * std
    return _last(bb_upper), _last(bb_mid), _last(bb_lower)


def volume_metrics(
    volumes: pd.Series, period: int = VOL_SMA_PERIOD
) -> tuple[int | None, float | None, float | None]:
    """Latest volume, 20-day SMA of volume, and their ratio.

    vol_daily is the most recent volume (integer). vol_sma_20 and vol_ratio need
    a full `period` of history; with fewer rows the rolling mean is NaN and both
    return None (the caller stores NULL) rather than crashing. vol_ratio is None
    if vol_sma_20 is missing or zero.
    """
    if len(volumes) == 0:
        return None, None, None
    vol_daily = int(volumes.iloc[-1])
    vol_sma = _last(volumes.rolling(period).mean())
    vol_sma_20 = _round2(vol_sma)
    if not vol_sma_20:  # None or zero — no usable baseline
        return vol_daily, vol_sma_20, None
    return vol_daily, vol_sma_20, _round2(vol_daily / vol_sma_20)


# ── Data access (read-only helpers) ───────────────────────────────────────────


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-only (used by tests / introspection)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_closes(conn: sqlite3.Connection, table: str, ticker: str) -> pd.DataFrame:
    """Return a date-ordered DataFrame of closes for one ticker (date, close)."""
    rows = conn.execute(
        f"SELECT date, close FROM {table} WHERE ticker = ? ORDER BY date ASC",
        (ticker,),
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    return pd.DataFrame(rows, columns=["date", "close"])


def _tail_closes(df: pd.DataFrame) -> pd.Series:
    """Last MAX_ROWS closes as a clean float Series (empty Series if no data)."""
    if df.empty:
        return pd.Series(dtype=float)
    return df["close"].astype(float).tail(MAX_ROWS).reset_index(drop=True)


def load_daily_volumes(conn: sqlite3.Connection, ticker: str) -> pd.Series:
    """Date-ordered daily volume Series for one ticker (empty if no data)."""
    rows = conn.execute(
        "SELECT volume FROM ohlcv_daily WHERE ticker = ? ORDER BY date ASC",
        (ticker,),
    ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series([r[0] for r in rows], dtype=float).tail(MAX_ROWS).reset_index(drop=True)


# ── Snapshot assembly ─────────────────────────────────────────────────────────


def build_snapshot(conn: sqlite3.Connection, ticker: str, analysis_date: str) -> dict:
    """Compute the full indicator row for one ticker across 3 timeframes.

    Daily drives latest_close / latest_date (the primary decision timeframe and
    the only feed guaranteed for a manual ticker). A ticker with no daily rows
    is a hard error — there is nothing to analyze.
    """
    daily_df = load_closes(conn, "ohlcv_daily", ticker)
    if daily_df.empty:
        raise ValueError(f"No daily OHLCV data for {ticker} — nothing to analyze.")

    latest_close = float(daily_df["close"].iloc[-1])
    latest_date = str(daily_df["date"].iloc[-1])

    daily = _tail_closes(daily_df)
    weekly = _tail_closes(load_closes(conn, "ohlcv_weekly", ticker))
    monthly = _tail_closes(load_closes(conn, "ohlcv_monthly", ticker))

    d_macd, d_sig, d_hist = macd(daily)
    d_bu, d_bm, d_bl = bollinger(daily)
    w_macd, w_sig, w_hist = macd(weekly)
    w_bu, w_bm, w_bl = bollinger(weekly)
    m_macd, m_sig, m_hist = macd(monthly)
    m_bu, m_bm, m_bl = bollinger(monthly)

    vol_daily, vol_sma_20, vol_ratio = volume_metrics(load_daily_volumes(conn, ticker))

    # _round2 every numeric value here so the DB write and the Obsidian note are
    # both fed identical 2-decimal values from this single source.
    return {
        "ticker": ticker,
        "analysis_date": analysis_date,
        "latest_close": _round2(latest_close),
        "latest_date": latest_date,
        # Daily
        "daily_sma50": _round2(sma(daily, DAILY_SMA_SHORT)),
        "daily_sma200": _round2(sma(daily, DAILY_SMA_LONG)),
        "daily_rsi14": _round2(rsi(daily)),
        "daily_macd": _round2(d_macd),
        "daily_macd_signal": _round2(d_sig),
        "daily_macd_hist": _round2(d_hist),
        "daily_bb_upper": _round2(d_bu),
        "daily_bb_mid": _round2(d_bm),
        "daily_bb_lower": _round2(d_bl),
        # Weekly
        "weekly_sma20": _round2(sma(weekly, WEEKLY_SMA_SHORT)),
        "weekly_sma50": _round2(sma(weekly, WEEKLY_SMA_LONG)),
        "weekly_rsi14": _round2(rsi(weekly)),
        "weekly_macd": _round2(w_macd),
        "weekly_macd_signal": _round2(w_sig),
        "weekly_macd_hist": _round2(w_hist),
        "weekly_bb_upper": _round2(w_bu),
        "weekly_bb_mid": _round2(w_bm),
        "weekly_bb_lower": _round2(w_bl),
        # Monthly
        "monthly_sma20": _round2(sma(monthly, MONTHLY_SMA)),
        "monthly_rsi14": _round2(rsi(monthly)),
        "monthly_macd": _round2(m_macd),
        "monthly_macd_signal": _round2(m_sig),
        "monthly_macd_hist": _round2(m_hist),
        "monthly_bb_upper": _round2(m_bu),
        "monthly_bb_mid": _round2(m_bm),
        "monthly_bb_lower": _round2(m_bl),
        # Daily volume — vol_sma_20 / vol_ratio are None when <20 daily rows.
        "vol_daily": vol_daily,
        "vol_sma_20": vol_sma_20,
        "vol_ratio": vol_ratio,
        # Calibration flags — per-instrument calibration is a future MANUAL step
        # (methodology §15.2 / §15.3). analyze.py never sets these to 1.
        "sma_pair_calibrated": 0,
        "rsi_calibrated": 0,
    }


# ── Persistence (SQLite first — must succeed) ─────────────────────────────────


def upsert_snapshot(conn: sqlite3.Connection, row: dict) -> None:
    """Insert or overwrite the snapshot for (ticker, analysis_date).

    A re-run on the same ticker+date overwrites the row (UPSERT) — never a
    duplicate. This must succeed; the caller treats a failure here as fatal for
    the ticker.
    """
    columns = SNAPSHOT_COLUMNS
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(columns)
    updates = ", ".join(
        f"{c} = excluded.{c}" for c in columns if c not in ("ticker", "analysis_date")
    )
    conn.execute(
        f"INSERT INTO indicator_snapshots ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(ticker, analysis_date) DO UPDATE SET {updates}",
        [row[c] for c in columns],
    )
    conn.commit()


# ── Obsidian (best-effort secondary sink) ─────────────────────────────────────


def _fmt(value: float | None) -> str:
    """Round to 2 decimals; None renders as N/A."""
    return "N/A" if value is None else f"{value:.2f}"


def build_note(row: dict) -> str:
    """Render the indicator snapshot as a markdown note. Research support only."""
    return f"""# {row["ticker"]} — Setup Analysis

> Research support only. Not a trade signal. No buy/sell recommendation.

**Analysis date:** {row["analysis_date"]}
**Latest close:** ₹{_fmt(row["latest_close"])} (as of {row["latest_date"]})
**H1 timeframe:** NOT AVAILABLE — ohlcv_1h table deferred

---

## Daily Indicators

| Indicator | Value |
|-----------|-------|
| SMA 50 | {_fmt(row["daily_sma50"])} |
| SMA 200 | {_fmt(row["daily_sma200"])} |
| RSI(14) | {_fmt(row["daily_rsi14"])} |
| MACD Line | {_fmt(row["daily_macd"])} |
| MACD Signal | {_fmt(row["daily_macd_signal"])} |
| MACD Histogram | {_fmt(row["daily_macd_hist"])} |
| BB Upper | {_fmt(row["daily_bb_upper"])} |
| BB Mid (SMA 20) | {_fmt(row["daily_bb_mid"])} |
| BB Lower | {_fmt(row["daily_bb_lower"])} |

## Weekly Indicators

| Indicator | Value |
|-----------|-------|
| SMA 20 | {_fmt(row["weekly_sma20"])} |
| SMA 50 | {_fmt(row["weekly_sma50"])} |
| RSI(14) | {_fmt(row["weekly_rsi14"])} |
| MACD Line | {_fmt(row["weekly_macd"])} |
| MACD Signal | {_fmt(row["weekly_macd_signal"])} |
| MACD Histogram | {_fmt(row["weekly_macd_hist"])} |
| BB Upper | {_fmt(row["weekly_bb_upper"])} |
| BB Mid (SMA 20) | {_fmt(row["weekly_bb_mid"])} |
| BB Lower | {_fmt(row["weekly_bb_lower"])} |

## Monthly Indicators

| Indicator | Value |
|-----------|-------|
| SMA 20 | {_fmt(row["monthly_sma20"])} |
| RSI(14) | {_fmt(row["monthly_rsi14"])} |
| MACD Line | {_fmt(row["monthly_macd"])} |
| MACD Signal | {_fmt(row["monthly_macd_signal"])} |
| MACD Histogram | {_fmt(row["monthly_macd_hist"])} |
| BB Upper | {_fmt(row["monthly_bb_upper"])} |
| BB Mid (SMA 20) | {_fmt(row["monthly_bb_mid"])} |
| BB Lower | {_fmt(row["monthly_bb_lower"])} |

---

## Calibration Status

| Parameter | Status |
|-----------|--------|
| SMA pair (per-instrument) | PENDING — empirical per methodology §15.2 |
| RSI thresholds (per-instrument) | PENDING — empirical per methodology §15.3 |

---
*Generated by NSE Trading Analyst · scripts/analyze.py · Paper trading only*
"""


def save_to_obsidian(
    note: str, ticker: str, api_key: str, host: str = "localhost"
) -> tuple[bool, str]:
    """PUT the note to 05-Watchlist/{TICKER}.md via the Obsidian Local REST API.

    Mirrors the stdlib urllib + self-signed-cert transport used by storage.py.
    Overwrites on rerun (PUT). Returns (success, message); never raises — the
    caller treats Obsidian as a best-effort sink after SQLite is already written.
    """
    path = f"{OBSIDIAN_VAULT_FOLDER}/{ticker}.md"
    url = f"https://{host}:27124/vault/{path}"
    try:
        req = urllib.request.Request(
            url,
            data=note.encode("utf-8"),
            method="PUT",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "text/markdown; charset=utf-8",
            },
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            if resp.status in (200, 201, 204):
                return True, f"Saved to {path}"
            return False, f"Unexpected status {resp.status}"
    except Exception as exc:  # noqa: BLE001 — best-effort; report, never abort
        return False, str(exc)


# ── Per-ticker orchestration ──────────────────────────────────────────────────


def analyze_ticker(
    conn: sqlite3.Connection,
    ticker: str,
    analysis_date: str,
    *,
    use_obsidian: bool,
    api_key: str | None,
    host: str,
) -> tuple[str, str | None]:
    """Compute + persist one ticker. SQLite write is fatal; Obsidian is not.

    Returns (obsidian_status, obsidian_message). The Obsidian call is wrapped so
    that even an unexpected raise can never undo the committed SQLite row.
    """
    row = build_snapshot(conn, ticker, analysis_date)
    upsert_snapshot(conn, row)  # must succeed — propagates on failure

    if not use_obsidian:
        return "skipped", None
    if not api_key:
        return "skipped", "OBSIDIAN_API_KEY not set"
    try:
        ok, message = save_to_obsidian(build_note(row), ticker, api_key, host)
        return ("saved" if ok else "failed"), message
    except Exception as exc:  # noqa: BLE001 — Obsidian must never block SQLite
        return "failed", str(exc)


def select_candidate_tickers(conn: sqlite3.Connection, scan_date: str) -> list[str]:
    """Distinct tickers in scan_results for the given scan_date."""
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM scan_results WHERE scan_date = ? ORDER BY ticker",
        (scan_date,),
    ).fetchall()
    return [r[0] for r in rows]


def run(ticker: str | None = None, use_obsidian: bool = True, db_path: Path = DB_PATH) -> int:
    """Entry point for both modes. Returns a process exit code (0 = ok)."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}. Run scripts/init_db.py first.")

    analysis_date = date.today().isoformat()
    api_key = os.environ.get("OBSIDIAN_API_KEY")
    host = os.environ.get("OBSIDIAN_HOST", "localhost")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if ticker:
            # Normalize manual input so 'reliance.ns' matches the stored 'RELIANCE.NS'.
            ticker = ticker.strip().upper()
            tickers = [ticker]
            print(f"Manual mode: analyzing {ticker} (analysis_date={analysis_date})")
        else:
            tickers = select_candidate_tickers(conn, analysis_date)
            if not tickers:
                print("0 candidates for today, exiting cleanly")
                return 0
            print(f"Default mode: {len(tickers)} candidate(s) for {analysis_date}")

        errors = 0
        for t in tickers:
            try:
                status, message = analyze_ticker(
                    conn,
                    t,
                    analysis_date,
                    use_obsidian=use_obsidian,
                    api_key=api_key,
                    host=host,
                )
                suffix = f" — {message}" if message else ""
                print(f"  {t:<16} snapshot saved · obsidian {status}{suffix}")
            except Exception as exc:  # noqa: BLE001 — isolate one bad ticker
                errors += 1
                print(f"  {t:<16} ERROR: {exc}")

        if errors:
            print(f"\nCompleted with {errors} error(s).")
            return 1
        return 0
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Per-ticker multi-timeframe indicator snapshot (research support only)."
    )
    parser.add_argument(
        "--ticker",
        help="Analyze this ticker directly off ohlcv_daily, bypassing scan_results.",
    )
    parser.add_argument(
        "--no-obsidian", action="store_true", help="Skip the Obsidian write entirely."
    )
    args = parser.parse_args()
    sys.exit(run(ticker=args.ticker, use_obsidian=not args.no_obsidian))


if __name__ == "__main__":
    main()
