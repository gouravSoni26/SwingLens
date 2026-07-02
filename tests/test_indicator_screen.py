"""Unit tests for scripts/indicator_screen.py (the derivation layer) and the
governance forbidden-words check over pages/4_Indicator_Screen.py's rendered
text (methodology.md §16).

Run:  pytest tests/test_indicator_screen.py -v

Pure derivation functions are tested on synthetic series/dataclasses — no
network, no real DB. Crosses/squeeze are tested by monkeypatching their
dependency (analyze.macd / _bb_width_series) so the test asserts THIS
module's branch logic, not analyze.py's indicator math (already covered by
test_analyze.py).
"""

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

# Make scripts/ and pages/ importable.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
PAGES_DIR = Path(__file__).resolve().parent.parent / "pages"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(PAGES_DIR))

import indicator_screen as ix  # noqa: E402
import screen  # noqa: E402
from brief import scan_forbidden  # noqa: E402

page = importlib.import_module("4_Indicator_Screen")


def L(kind: str, low: float, high: float | None = None) -> screen.Level:
    return screen.Level(kind=kind, low=low, high=high)


# ── SMA-pair cross (real analyze.sma, period=1 trick for exact hand-verification) ─
# sma(closes, 1) == closes.iloc[-1] since rolling(1).mean() is the identity.


def test_sma_pair_cross_up_when_short_crosses_above_long():
    closes = pd.Series([10.0, 10.0, 3.0, 20.0])
    assert ix.sma_pair_cross(closes, 1, 2) == "up"


def test_sma_pair_cross_down_when_short_crosses_below_long():
    closes = pd.Series([3.0, 3.0, 10.0, 1.0])
    assert ix.sma_pair_cross(closes, 1, 2) == "down"


def test_sma_pair_cross_none_when_flat():
    closes = pd.Series([10.0, 10.0, 10.0, 10.0])
    assert ix.sma_pair_cross(closes, 1, 2) is None


def test_sma_pair_cross_none_when_insufficient_history():
    assert ix.sma_pair_cross(pd.Series([1.0]), 1, 2) is None


# ── MACD cross (mocked analyze.macd — isolates this module's branch logic) ───


def test_macd_cross_up_when_line_crosses_above_signal(monkeypatch):
    def fake_macd(closes, *_a, **_kw):
        return (5.0, 3.0, 2.0) if len(closes) == 5 else (1.0, 2.0, -1.0)

    monkeypatch.setattr(ix.analyze, "macd", fake_macd)
    assert ix.macd_cross(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])) == "up"


def test_macd_cross_down_when_line_crosses_below_signal(monkeypatch):
    def fake_macd(closes, *_a, **_kw):
        return (1.0, 2.0, -1.0) if len(closes) == 5 else (5.0, 3.0, 2.0)

    monkeypatch.setattr(ix.analyze, "macd", fake_macd)
    assert ix.macd_cross(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])) == "down"


def test_macd_cross_none_when_no_transition(monkeypatch):
    monkeypatch.setattr(ix.analyze, "macd", lambda closes, *_a, **_kw: (5.0, 3.0, 2.0))
    assert ix.macd_cross(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])) is None


def test_macd_cross_none_when_insufficient_history():
    assert ix.macd_cross(pd.Series([1.0])) is None


# ── Squeeze (mocked _bb_width_series — isolates the min-over-window check) ───


def test_squeeze_lit_true_when_current_width_is_window_minimum(monkeypatch):
    widths = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0])
    monkeypatch.setattr(ix, "_bb_width_series", lambda closes, period=ix.BB_PERIOD: widths)
    assert ix.squeeze_lit(pd.Series([0.0] * 5), lookback=5) is True


def test_squeeze_lit_false_when_current_width_is_not_minimum(monkeypatch):
    widths = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    monkeypatch.setattr(ix, "_bb_width_series", lambda closes, period=ix.BB_PERIOD: widths)
    assert ix.squeeze_lit(pd.Series([0.0] * 5), lookback=5) is False


def test_squeeze_lit_false_when_insufficient_width_history(monkeypatch):
    widths = pd.Series([5.0, 4.0])
    monkeypatch.setattr(ix, "_bb_width_series", lambda closes, period=ix.BB_PERIOD: widths)
    assert ix.squeeze_lit(pd.Series([0.0] * 2), lookback=5) is False


# ── Simple lit-up predicates ───────────────────────────────────────────────


def test_rsi_lit_below_low():
    assert ix.rsi_lit(25.0) is True


def test_rsi_lit_above_high():
    assert ix.rsi_lit(75.0) is True


def test_rsi_lit_false_inside_band():
    assert ix.rsi_lit(50.0) is False


def test_rsi_lit_false_when_none():
    assert ix.rsi_lit(None) is False


def test_bb_position_upper_when_close_at_or_above_band():
    assert ix.bb_position(105.0, 100.0, 90.0) == "upper"


def test_bb_position_lower_when_close_at_or_below_band():
    assert ix.bb_position(85.0, 100.0, 90.0) == "lower"


def test_bb_position_middle_when_between_bands():
    assert ix.bb_position(95.0, 100.0, 90.0) == "middle"


def test_bb_position_none_when_input_missing():
    assert ix.bb_position(None, 100.0, 90.0) is None


def test_bb_lit_true_for_band_positions():
    assert ix.bb_lit("upper") is True
    assert ix.bb_lit("lower") is True


def test_bb_lit_false_for_middle_or_none():
    assert ix.bb_lit("middle") is False
    assert ix.bb_lit(None) is False


def test_vol_lit_strong_at_or_above_threshold():
    assert ix.vol_lit(6.0) == "strong"


def test_vol_lit_notable_at_or_above_threshold():
    assert ix.vol_lit(2.5) == "notable"


def test_vol_lit_none_below_notable():
    assert ix.vol_lit(1.0) is None


def test_vol_lit_none_when_missing():
    assert ix.vol_lit(None) is None


def test_sr_state_support_within_proximity():
    levels = [L("support", 100.0, 105.0)]
    assert ix.sr_state(103.0, levels) == "support"


def test_sr_state_none_outside_proximity():
    levels = [L("support", 100.0, 105.0)]
    assert ix.sr_state(200.0, levels) is None


def test_sr_state_none_when_no_levels():
    assert ix.sr_state(100.0, []) is None


def test_macd_position_above_and_below():
    assert ix.macd_position(5.0, 3.0) == "above"
    assert ix.macd_position(3.0, 5.0) == "below"


def test_macd_position_none_when_missing():
    assert ix.macd_position(None, 3.0) is None


def test_sma_pair_position_above_and_below():
    assert ix.sma_pair_position(5.0, 3.0) == "above"
    assert ix.sma_pair_position(3.0, 5.0) == "below"


def test_candle_color_green_and_red():
    assert ix.candle_color(100.0, 105.0) == "green"
    assert ix.candle_color(100.0, 95.0) == "red"


def test_candle_color_none_when_missing():
    assert ix.candle_color(None, 95.0) is None


# ── Agreement facts (§16.1 rule 3 — reports agreement, never a verdict) ──────


def test_agreement_fact_when_all_timeframes_match():
    values = {"daily": "up", "weekly": "up", "monthly": "up"}
    assert ix.agreement_fact("MACD crossed", values) == "MACD crossed up on all three timeframes"


def test_agreement_fact_none_when_timeframes_disagree():
    values = {"daily": "up", "weekly": "down", "monthly": "up"}
    assert ix.agreement_fact("MACD crossed", values) is None


def test_agreement_fact_none_when_any_value_missing():
    values = {"daily": "up", "weekly": None, "monthly": "up"}
    assert ix.agreement_fact("MACD crossed", values) is None


# ── Governance: no forbidden directional/verdict words in rendered text ──────
# FORBIDDEN_WORDS (brief.py): suggests, implies, indicates direction, supports,
# expects, likely, momentum building, breakout expected, continuation,
# reversal, forecast, prediction, signal, buy, sell, recommend.


def _maximal_timeframe_facts(timeframe: str, direction: str) -> ix.TimeframeFacts:
    """Every lit-up branch fires, in one direction, for one timeframe."""
    pairs = {pair: direction for pair in ix.SMA_PAIRS}
    positions = {pair: ("above" if direction == "up" else "below") for pair in ix.SMA_PAIRS}
    return ix.TimeframeFacts(
        timeframe=timeframe,
        close=105.0,
        rsi14=15.0 if direction == "up" else 85.0,
        rsi_lit=True,
        macd_position="above" if direction == "up" else "below",
        macd_cross=direction,
        sma_pair_positions=positions,
        sma_pair_crosses=pairs,
        bb_position="upper" if direction == "up" else "lower",
        bb_lit=True,
        squeeze=True,
        sr_state="resistance" if direction == "up" else "support",
        candle="green" if direction == "up" else "red",
    )


@pytest.fixture
def maximal_ticker_facts() -> ix.TickerFacts:
    """Every derivation branch lit, across all three timeframes, both
    directions represented — the governance scan's worst case."""
    return ix.TickerFacts(
        ticker="TEST.NS",
        analysis_date="2026-07-02",
        latest_close=105.0,
        timeframes={
            "daily": _maximal_timeframe_facts("daily", "up"),
            "weekly": _maximal_timeframe_facts("weekly", "down"),
            "monthly": _maximal_timeframe_facts("monthly", "up"),
        },
        vol_ratio=6.0,
        vol_lit="strong",
    )


def _all_rendered_strings(facts: ix.TickerFacts) -> list[str]:
    """Every string pages/4_Indicator_Screen.py can put on screen for one
    ticker: watchlist chips, alignment columns, alignment agreement facts,
    every timeframe's Style C body, and the volume line.
    """
    strings = list(page.ticker_chips(facts))
    for timeframe in ix.TIMEFRAMES:
        tfacts = facts.timeframes[timeframe]
        strings.extend(page.build_alignment_column_lines(tfacts))
        strings.extend(page.build_timeframe_lines(timeframe, tfacts))
    strings.extend(page._alignment_facts(facts))
    volume_line = page.build_volume_line(facts)
    if volume_line:
        strings.append(volume_line)
    strings.append(page.DISCLAIMER)
    return strings


def test_no_forbidden_words_in_any_rendered_string(maximal_ticker_facts):
    rendered = _all_rendered_strings(maximal_ticker_facts)
    combined = "\n".join(rendered)
    found = scan_forbidden(combined)
    assert found == [], f"forbidden word(s) leaked into rendered text: {found}\n\n{combined}"


def test_no_forbidden_words_in_nothing_lit_watchlist_row():
    """A ticker with nothing lit still renders governance-clean text."""
    empty_tf = ix.TimeframeFacts(
        timeframe="daily",
        close=100.0,
        rsi14=50.0,
        rsi_lit=False,
        macd_position="above",
        macd_cross=None,
        sma_pair_positions={p: "above" for p in ix.SMA_PAIRS},
        sma_pair_crosses={p: None for p in ix.SMA_PAIRS},
        bb_position="middle",
        bb_lit=False,
        squeeze=False,
        sr_state=None,
        candle="green",
    )
    facts = ix.TickerFacts(
        ticker="QUIET.NS",
        analysis_date="2026-07-02",
        latest_close=100.0,
        timeframes={tf: empty_tf for tf in ix.TIMEFRAMES},
        vol_ratio=1.0,
        vol_lit=None,
    )
    chips = page.ticker_chips(facts)
    assert chips == []
    assert scan_forbidden(page.NOTHING_LIT) == []
