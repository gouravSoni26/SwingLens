"""Unit + integration tests for scripts/analyze.py.

Run:  pytest tests/test_analyze.py -v

Pure indicator functions are tested on synthetic series. The orchestration paths
(zero-candidate exit, Obsidian-failure isolation, UPSERT idempotency) run against
a temporary on-disk SQLite DB seeded with synthetic OHLCV — no network. One
integration test reads the real data/analyses.db (skipped if it is absent).
"""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import analyze  # noqa: E402
import init_db  # noqa: E402

REAL_DB = Path(__file__).resolve().parent.parent / "data" / "analyses.db"


# ── Synthetic series helpers ──────────────────────────────────────────────────


def _rising(n: int, start: float = 100.0, step: float = 1.0) -> pd.Series:
    return pd.Series([start + step * i for i in range(n)])


def _wave(n: int) -> pd.Series:
    """A non-flat oscillating-but-drifting series (gains and losses both occur)."""
    return pd.Series([100.0 + (i % 7) - 3.0 + i * 0.1 for i in range(n)])


# ── 1. RSI in [0, 100] ────────────────────────────────────────────────────────


def test_rsi_between_0_and_100_on_synthetic_series():
    for series in (_rising(100), _rising(100, start=200.0, step=-1.0), _wave(120)):
        value = analyze.rsi(series)
        assert value is not None
        assert 0.0 <= value <= 100.0


# ── 2. MACD histogram identity ────────────────────────────────────────────────


def test_macd_histogram_equals_line_minus_signal():
    macd_line, signal_line, histogram = analyze.macd(_wave(120))
    assert histogram == pytest.approx(macd_line - signal_line, abs=1e-9)


# ── 3. Bollinger ordering ─────────────────────────────────────────────────────


def test_bollinger_upper_gt_mid_gt_lower_for_non_flat_series():
    upper, mid, lower = analyze.bollinger(_wave(60))
    assert upper > mid > lower


# ── 3c. sma_set — all SMA_PERIODS, one call per timeframe (§12.1, §16.2) ──────


def test_sma_set_returns_every_period_keyed_by_prefix():
    result = analyze.sma_set("daily", _wave(250))
    expected_keys = {f"daily_sma{period}" for period in analyze.SMA_PERIODS}
    assert set(result.keys()) == expected_keys


def test_sma_set_none_when_insufficient_history():
    # Only 30 rows: sma20 computable, sma50+ are not (insufficient history).
    result = analyze.sma_set("daily", _wave(30))
    assert result["daily_sma20"] is not None
    assert result["daily_sma50"] is None
    assert result["daily_sma200"] is None


# ── 3b. Volume metrics ────────────────────────────────────────────────────────


def _volumes(n: int, start: int = 1000, step: int = 10) -> pd.Series:
    return pd.Series([start + step * i for i in range(n)], dtype=float)


def test_volume_metrics_full_history():
    vol_daily, vol_sma_20, vol_ratio = analyze.volume_metrics(_volumes(60))
    assert isinstance(vol_daily, int) and vol_daily > 0
    assert isinstance(vol_sma_20, float) and vol_sma_20 > 0
    assert isinstance(vol_ratio, float) and vol_ratio > 0
    assert vol_ratio == pytest.approx(vol_daily / vol_sma_20, abs=0.01)


def test_volume_metrics_fewer_than_20_rows_is_none():
    vol_daily, vol_sma_20, vol_ratio = analyze.volume_metrics(_volumes(10))
    assert vol_daily == 1090  # latest is still available
    assert vol_sma_20 is None
    assert vol_ratio is None


# ── Temp-DB scaffolding ───────────────────────────────────────────────────────


def _make_db(tmp_path: Path, seed_ticker: str | None = None, n_daily: int = 260) -> str:
    """Create a temp DB with the tables analyze.py touches; optionally seed one ticker."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    try:
        init_db.init_indicator_snapshots(conn)  # real schema, stays in sync
        conn.execute(
            "CREATE TABLE scan_results (scan_date DATE, ticker TEXT, "
            "latest_date DATE, latest_close REAL)"
        )
        for tf in ("ohlcv_daily", "ohlcv_weekly", "ohlcv_monthly"):
            conn.execute(
                f"CREATE TABLE {tf} (ticker TEXT, date TEXT, open REAL, high REAL, "
                "low REAL, close REAL, volume INTEGER)"
            )
        if seed_ticker:
            _seed_ohlcv(conn, seed_ticker, n_daily)
        conn.commit()
    finally:
        conn.close()
    return str(db)


def _seed_ohlcv(conn: sqlite3.Connection, ticker: str, n_daily: int) -> None:
    closes = _wave(n_daily).tolist()
    base = date.today()
    for table, count in (
        ("ohlcv_daily", n_daily),
        ("ohlcv_weekly", min(n_daily, 120)),
        ("ohlcv_monthly", min(n_daily, 60)),
    ):
        rows = [
            (
                ticker,
                (base - timedelta(days=count - 1 - i)).isoformat(),
                c,
                c,
                c,
                c,
                1000,
            )
            for i, c in enumerate(closes[:count])
        ]
        conn.executemany(
            f"INSERT INTO {table} (ticker, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


# ── 4. Manual mode with a known ticker (real DB) ──────────────────────────────


@pytest.mark.skipif(not REAL_DB.exists(), reason="populated data/analyses.db required")
def test_manual_mode_known_ticker_has_daily_rsi():
    conn = analyze.open_readonly(REAL_DB)
    try:
        row = analyze.build_snapshot(conn, "RELIANCE.NS", date.today().isoformat())
    finally:
        conn.close()
    assert row["daily_rsi14"] is not None
    assert 0.0 <= row["daily_rsi14"] <= 100.0


@pytest.mark.skipif(not REAL_DB.exists(), reason="populated data/analyses.db required")
def test_manual_mode_known_ticker_has_all_new_sma_columns():
    conn = analyze.open_readonly(REAL_DB)
    try:
        row = analyze.build_snapshot(conn, "RELIANCE.NS", date.today().isoformat())
    finally:
        conn.close()
    for timeframe in ("daily", "weekly", "monthly"):
        for period in analyze.SMA_PERIODS:
            assert row[f"{timeframe}_sma{period}"] is not None


# ── 5. Zero-candidate default mode exits cleanly ──────────────────────────────


def test_default_mode_zero_candidates_exits_clean(tmp_path, capsys):
    db = _make_db(tmp_path)  # scan_results empty
    exit_code = analyze.run(ticker=None, use_obsidian=False, db_path=db)
    assert exit_code == 0
    assert "0 candidates for today, exiting cleanly" in capsys.readouterr().out


# ── 6. Obsidian failure does not block the SQLite write ───────────────────────


def test_obsidian_failure_does_not_block_sqlite(tmp_path, monkeypatch):
    db = _make_db(tmp_path, seed_ticker="TEST.NS")

    def boom(*args, **kwargs):
        raise RuntimeError("obsidian down")

    monkeypatch.setattr(analyze, "save_to_obsidian", boom)
    monkeypatch.setenv("OBSIDIAN_API_KEY", "dummy-key")

    exit_code = analyze.run(ticker="TEST.NS", use_obsidian=True, db_path=db)
    assert exit_code == 0  # the raise is isolated; the ticker did not fail

    conn = sqlite3.connect(db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM indicator_snapshots WHERE ticker = 'TEST.NS'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1  # SQLite row persisted despite Obsidian raising


# ── 7. UPSERT idempotency — rerun overwrites, never duplicates ────────────────


def test_upsert_no_duplicate_on_rerun(tmp_path):
    db = _make_db(tmp_path, seed_ticker="TEST.NS")
    analyze.run(ticker="TEST.NS", use_obsidian=False, db_path=db)
    analyze.run(ticker="TEST.NS", use_obsidian=False, db_path=db)

    conn = sqlite3.connect(db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM indicator_snapshots WHERE ticker = 'TEST.NS'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1
