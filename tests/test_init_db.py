"""Unit tests for scripts/init_db.py's Indicator Screen schema additions
(methodology.md §16): the 13 new indicator_snapshots SMA columns and the new
squeeze_reviews table.

Run:  pytest tests/test_init_db.py -v

Runs against a temporary on-disk SQLite DB (init_db.py requires the DB file to
already exist, mirroring storage.py's role) — no network, never touches
data/analyses.db.
"""

import sqlite3
import sys
from pathlib import Path

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import init_db  # noqa: E402

NEW_SMA_COLUMNS = [
    "daily_sma20",
    "daily_sma98",
    "daily_sma100",
    "daily_sma198",
    "weekly_sma98",
    "weekly_sma100",
    "weekly_sma198",
    "weekly_sma200",
    "monthly_sma50",
    "monthly_sma98",
    "monthly_sma100",
    "monthly_sma198",
    "monthly_sma200",
]


def _empty_db(tmp_path: Path) -> Path:
    """An empty SQLite file — init_db.init_db() requires the file to already
    exist (mirrors storage.py creating data/analyses.db first)."""
    db_path = tmp_path / "test.db"
    sqlite3.connect(db_path).close()
    return db_path


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_init_db_raises_on_missing_db_file(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    try:
        init_db.init_db(missing)
        raised = False
    except FileNotFoundError:
        raised = True
    assert raised


def test_init_db_adds_all_13_new_sma_columns(tmp_path):
    db_path = _empty_db(tmp_path)
    init_db.init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = _columns(conn, "indicator_snapshots")
    finally:
        conn.close()

    missing = [c for c in NEW_SMA_COLUMNS if c not in columns]
    assert missing == []


def test_init_db_preserves_existing_sma_columns(tmp_path):
    db_path = _empty_db(tmp_path)
    init_db.init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = _columns(conn, "indicator_snapshots")
    finally:
        conn.close()

    existing = {"daily_sma50", "daily_sma200", "weekly_sma20", "weekly_sma50", "monthly_sma20"}
    assert existing.issubset(columns)


def test_init_db_creates_squeeze_reviews_table(tmp_path):
    db_path = _empty_db(tmp_path)
    init_db.init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='squeeze_reviews'"
        ).fetchone()
        columns = _columns(conn, "squeeze_reviews")
    finally:
        conn.close()

    assert exists is not None
    assert columns == {
        "id",
        "ticker",
        "timeframe",
        "review_date",
        "verdict",
        "note",
        "outcome",
        "created_at",
    }


def test_squeeze_reviews_enforces_unique_ticker_timeframe_date(tmp_path):
    db_path = _empty_db(tmp_path)
    init_db.init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO squeeze_reviews (ticker, timeframe, review_date, verdict) "
            "VALUES ('TEST.NS', 'daily', '2026-07-02', 'real')"
        )
        conn.commit()
        try:
            conn.execute(
                "INSERT INTO squeeze_reviews (ticker, timeframe, review_date, verdict) "
                "VALUES ('TEST.NS', 'daily', '2026-07-02', 'noise')"
            )
            conn.commit()
            raised = False
        except sqlite3.IntegrityError:
            raised = True
    finally:
        conn.close()
    assert raised


def test_init_db_is_idempotent_on_rerun(tmp_path):
    db_path = _empty_db(tmp_path)
    init_db.init_db(db_path)
    init_db.init_db(db_path)  # must not raise or duplicate columns/tables

    conn = sqlite3.connect(db_path)
    try:
        columns = _columns(conn, "indicator_snapshots")
        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='squeeze_reviews'"
        ).fetchone()[0]
    finally:
        conn.close()

    missing = [c for c in NEW_SMA_COLUMNS if c not in columns]
    assert missing == []
    assert table_count == 1  # exactly one squeeze_reviews table, not duplicated
