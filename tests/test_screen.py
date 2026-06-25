"""Unit tests for the screening rules, freshness gate, and classification.

Run:  pytest tests/test_screen.py -v

Exercises the pure rule/geometry functions and screen_ticker against an
in-memory SQLite DB seeded with synthetic OHLCV and curated S/R levels — no
network, no real data.
"""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import screen  # noqa: E402


def L(kind: str, low: float, high: float | None = None) -> "screen.Level":
    return screen.Level(kind=kind, low=low, high=high)


def _rising(n: int, start: float = 100.0, step: float = 1.0) -> pd.Series:
    return pd.Series([start + step * i for i in range(n)])


# ── Rule 1: S/R proximity (curated zones) ────────────────────────────────────

def test_sr_proximity_passes_within_threshold():
    # Arrange: resistance at 100, close 101 (1% away < 2%).
    assert screen.rule_sr_proximity(101.0, [L("resistance", 100.0)]) is True


def test_sr_proximity_fails_outside_threshold():
    assert screen.rule_sr_proximity(105.0, [L("resistance", 100.0)]) is False


def test_sr_proximity_fails_with_no_levels():
    # Empty curated levels must never count as "near".
    assert screen.rule_sr_proximity(100.0, []) is False


def test_sr_proximity_zero_distance_inside_zone():
    # Close inside a [100, 105] zone => distance 0 => within threshold.
    assert screen.rule_sr_proximity(102.0, [L("support", 100.0, 105.0)]) is True


# ── Rule 2: breakout (close-basis, wicks excluded, LONG_ONLY) ────────────────

def test_breakout_up_when_close_crosses_resistance():
    closes = pd.Series([95.0, 96.0, 99.0, 101.0])
    assert screen.rule_breakout(closes, [L("resistance", 100.0)]) == "up"


def test_breakout_up_uses_zone_upper_bound():
    # Resistance zone [100, 102]: must close above the UPPER bound to break out.
    closes = pd.Series([98.0, 99.0, 101.0, 103.0])
    assert screen.rule_breakout(closes, [L("resistance", 100.0, 102.0)]) == "up"
    # A close at 101 (inside the zone) is not yet a breakout.
    inside = pd.Series([98.0, 99.0, 100.5, 101.0])
    assert screen.rule_breakout(inside, [L("resistance", 100.0, 102.0)]) is None


def test_breakout_long_only_excludes_down_breakout():
    closes = pd.Series([105.0, 104.0, 101.0, 99.0])
    assert screen.rule_breakout(closes, [L("support", 100.0)], long_only=True) is None
    assert screen.rule_breakout(closes, [L("support", 100.0)], long_only=False) == "down"


def test_no_breakout_when_close_stays_below_resistance():
    closes = pd.Series([95.0, 96.0, 98.0, 99.5])
    assert screen.rule_breakout(closes, [L("resistance", 100.0)]) is None


# ── Level geometry & zero guard ──────────────────────────────────────────────

def test_level_distance_zero_inside_zone():
    assert screen.level_distance_pct(102.0, L("support", 100.0, 105.0)) == 0.0


def test_level_distance_zero_guard_does_not_crash():
    # A degenerate 0 level must not raise ZeroDivisionError.
    assert screen.level_distance_pct(10.0, L("support", 0.0)) == float("inf")


# ── Rule 3: SMA trend alignment + sideways exclusion ─────────────────────────

def test_sma_alignment_passes_for_clean_uptrend():
    passed, smas = screen.rule_sma_trend(_rising(260), _rising(60))
    assert passed is True
    assert smas["daily_sma50"] > smas["daily_sma200"]


def test_sma_alignment_fails_when_sideways():
    passed, _ = screen.rule_sma_trend(pd.Series([100.0] * 260), pd.Series([100.0] * 60))
    assert passed is False


def test_sma_alignment_fails_on_downtrend():
    passed, _ = screen.rule_sma_trend(
        _rising(260, start=400.0, step=-1.0), _rising(60, start=160.0, step=-1.0)
    )
    assert passed is False


# ── Freshness ────────────────────────────────────────────────────────────────

def test_is_stale():
    ref = date(2026, 6, 18)
    assert screen.is_stale("2026-06-10", 5, today=ref) is True    # 8 days > 5
    assert screen.is_stale("2026-06-15", 5, today=ref) is False   # 3 days
    assert screen.is_stale("2026-06-01", 8, today=ref) is True    # 17 days > 8


# ── Edge-case classification via screen_ticker ───────────────────────────────

@pytest.fixture
def db():
    """In-memory DB with the tables screen_ticker reads."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for tf in ("ohlcv_daily", "ohlcv_weekly"):
        conn.execute(f"CREATE TABLE {tf} (ticker TEXT, date TEXT, close REAL)")
    conn.execute(
        """CREATE TABLE support_resistance
           (ticker TEXT, timeframe TEXT, kind TEXT,
            level_low REAL, level_high REAL, is_active INTEGER DEFAULT 1)"""
    )
    yield conn
    conn.close()


def _seed_ohlcv(conn, table, ticker, closes, end_days_ago: int = 0):
    """Seed closes ending end_days_ago calendar days before today (0 = fresh today)."""
    n = len(closes)
    last = date.today() - timedelta(days=end_days_ago)
    rows = [
        (ticker, (last - timedelta(days=n - 1 - i)).isoformat(), c)
        for i, c in enumerate(closes)
    ]
    conn.executemany(f"INSERT INTO {table} (ticker, date, close) VALUES (?, ?, ?)", rows)
    conn.commit()


def _seed_level(conn, ticker, kind, low, high=None):
    conn.execute(
        "INSERT INTO support_resistance (ticker, timeframe, kind, level_low, level_high) "
        "VALUES (?, 'daily', ?, ?, ?)",
        (ticker, kind, low, high),
    )
    conn.commit()


def test_screen_ticker_insufficient_history(db):
    _seed_ohlcv(db, "ohlcv_daily", "TEST.NS", _rising(10).tolist())
    _seed_ohlcv(db, "ohlcv_weekly", "TEST.NS", _rising(10).tolist())
    assert screen.screen_ticker(db, "TEST.NS").status == "insufficient_history"


def test_screen_ticker_stale_daily(db):
    # Enough history, but the daily feed ends 30 days ago => stale (skipped).
    _seed_ohlcv(db, "ohlcv_daily", "OLD.NS", _rising(260).tolist(), end_days_ago=30)
    _seed_ohlcv(db, "ohlcv_weekly", "OLD.NS", _rising(60).tolist())  # fresh
    _seed_level(db, "OLD.NS", "resistance", 358.5)
    assert screen.screen_ticker(db, "OLD.NS").status == "stale"


def test_screen_ticker_no_levels_when_table_empty(db):
    # Fresh, sufficient history, but no curated levels => skipped (pure manual).
    _seed_ohlcv(db, "ohlcv_daily", "NOLVL.NS", _rising(260).tolist())
    _seed_ohlcv(db, "ohlcv_weekly", "NOLVL.NS", _rising(60).tolist())
    assert screen.screen_ticker(db, "NOLVL.NS").status == "no_levels"


def test_screen_ticker_candidate_passes_all_three(db):
    # Rising series (bullish SMAs), fresh, with a resistance just below the last
    # close so the final close breaks out and proximity is within 2%.
    closes = _rising(260).tolist()  # last two closes: 358.0, 359.0
    _seed_ohlcv(db, "ohlcv_daily", "UP.NS", closes)
    _seed_ohlcv(db, "ohlcv_weekly", "UP.NS", _rising(60).tolist())
    _seed_level(db, "UP.NS", "resistance", 358.5)
    result = screen.screen_ticker(db, "UP.NS")
    assert result.status == "candidate"
    assert result.breakout_kind == "up"
    assert result.nearest_level_kind == "resistance"


# ── Obsidian note: Needs Attention + Rule-by-Rule Breakdown ──────────────────

def _tally(
    *,
    no_levels_tickers=None,
    insufficient_tickers=None,
    stale_tickers=None,
    total: int = 100,
    errors: int = 0,
) -> dict:
    """Build a tally dict shaped exactly as run_screen() passes to build_scan_note."""
    no_levels_tickers = no_levels_tickers or []
    insufficient_tickers = insufficient_tickers or []
    stale_tickers = stale_tickers or []
    return {
        "total": total,
        "scanned": total - errors,
        "no_levels": len(no_levels_tickers),
        "no_levels_tickers": no_levels_tickers,
        "insufficient": len(insufficient_tickers),
        "insufficient_tickers": insufficient_tickers,
        "stale": len(stale_tickers),
        "stale_tickers": stale_tickers,
        "errors": errors,
    }


def test_needs_attention_lists_insufficient_ticker_name():
    # A non-empty insufficient-history bucket must surface the actual ticker.
    note = screen.build_scan_note(
        "2026-06-22",
        candidates=[],
        rejected=[],
        tally=_tally(insufficient_tickers=["NEWLY.NS"]),
    )
    assert "## ⚠️ Needs Attention" in note
    assert "Insufficient history" in note
    assert "NEWLY.NS" in note


def test_needs_attention_truncates_long_no_levels_list():
    # > 10 no-levels tickers => first 10 shown, remainder summarised.
    names = [f"T{i:02d}.NS" for i in range(13)]  # 13 names => 3 over the limit
    note = screen.build_scan_note(
        "2026-06-22",
        candidates=[],
        rejected=[],
        tally=_tally(no_levels_tickers=names),
    )
    assert "T00.NS" in note          # first shown
    assert "T09.NS" in note          # 10th shown (limit boundary)
    assert "T10.NS" not in note      # 11th truncated away
    assert "... and 3 more" in note
    # Count cell still reflects the full bucket size, not the truncated view.
    assert "| No S/R levels curated | 13 |" in note


def test_needs_attention_section_omitted_on_clean_run():
    # All three skip buckets empty => no Needs Attention section at all.
    note = screen.build_scan_note(
        "2026-06-22",
        candidates=[],
        rejected=[],
        tally=_tally(),
    )
    assert "Needs Attention" not in note


def test_rule_breakdown_shows_first_failed_rule():
    # A rejected name that failed Rule 2 reports "R2" as the drop point.
    rejected = [
        screen.ScreenResult(
            ticker="REJ.NS",
            status="rejected",
            latest_close=250.0,
            r1_passed=True,
            r2_passed=False,
            r3_passed=True,
        )
    ]
    note = screen.build_scan_note(
        "2026-06-22",
        candidates=[],
        rejected=rejected,
        tally=_tally(),
    )
    assert "## Rule-by-Rule Breakdown" in note
    assert "REJ.NS" in note
    assert "| REJ.NS | 250.00 | pass | fail | pass | R2 |" in note
