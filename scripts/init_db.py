"""Phase 3 schema initialization for NSE Trading Analyst.

Adds the OHLCV pipeline tables alongside the existing ``analyses`` table in
``data/analyses.db``. Safe to run multiple times: every CREATE statement uses
IF NOT EXISTS, so re-running is a no-op against tables that already exist.

Schema source of truth: docs/phase3-schema.md
Usage:  python scripts/init_db.py

Stdlib only (sqlite3, pathlib) — no third-party dependencies.
"""

import sqlite3
from pathlib import Path

# DB lives at <repo>/data/analyses.db regardless of where the script is run from.
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "analyses.db"

# Each entry is executed in order. Tables before their indexes.
SCHEMA_STATEMENTS = [
    # 1. instruments — single source of truth for the Nifty 500 universe
    """
    CREATE TABLE IF NOT EXISTS instruments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker      TEXT NOT NULL UNIQUE,
        name        TEXT NOT NULL,
        sector      TEXT,
        is_active   INTEGER NOT NULL DEFAULT 1,
        added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_instruments_ticker ON instruments(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_instruments_sector ON instruments(sector)",
    "CREATE INDEX IF NOT EXISTS idx_instruments_active ON instruments(is_active)",
    # 2. ohlcv_daily — daily candles, 2yr lookback on initial fetch
    """
    CREATE TABLE IF NOT EXISTS ohlcv_daily (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker       TEXT NOT NULL,
        date         DATE NOT NULL,
        open         REAL NOT NULL,
        high         REAL NOT NULL,
        low          REAL NOT NULL,
        close        REAL NOT NULL,
        volume       INTEGER NOT NULL,
        fetched_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(ticker, date),
        FOREIGN KEY (ticker) REFERENCES instruments(ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_ticker_date ON ohlcv_daily(ticker, date)",
    # 3. ohlcv_weekly — weekly candles, 8yr lookback on initial fetch
    """
    CREATE TABLE IF NOT EXISTS ohlcv_weekly (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker       TEXT NOT NULL,
        date         DATE NOT NULL,
        open         REAL NOT NULL,
        high         REAL NOT NULL,
        low          REAL NOT NULL,
        close        REAL NOT NULL,
        volume       INTEGER NOT NULL,
        fetched_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(ticker, date),
        FOREIGN KEY (ticker) REFERENCES instruments(ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ohlcv_weekly_ticker_date ON ohlcv_weekly(ticker, date)",
    # 4. ohlcv_monthly — monthly candles, all available history on initial fetch
    """
    CREATE TABLE IF NOT EXISTS ohlcv_monthly (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker       TEXT NOT NULL,
        date         DATE NOT NULL,
        open         REAL NOT NULL,
        high         REAL NOT NULL,
        low          REAL NOT NULL,
        close        REAL NOT NULL,
        volume       INTEGER NOT NULL,
        fetched_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(ticker, date),
        FOREIGN KEY (ticker) REFERENCES instruments(ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ohlcv_monthly_ticker_date ON ohlcv_monthly(ticker, date)",
    # 5. fetch_log — records every fetcher run for health monitoring
    """
    CREATE TABLE IF NOT EXISTS fetch_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        run_type        TEXT NOT NULL,
        timeframe       TEXT NOT NULL,
        batch_number    INTEGER,
        tickers_total   INTEGER NOT NULL,
        tickers_success INTEGER NOT NULL,
        tickers_failed  INTEGER NOT NULL DEFAULT 0,
        failed_tickers  TEXT,
        status          TEXT NOT NULL,
        error_message   TEXT,
        duration_seconds REAL
    )
    """,
    # 6. trades — skeleton trades journal, joins instruments and analyses
    """
    CREATE TABLE IF NOT EXISTS trades (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT NOT NULL,
        direction       TEXT NOT NULL DEFAULT 'long',
        status          TEXT NOT NULL DEFAULT 'open',
        entry_date      DATE,
        exit_date       DATE,
        entry_price     REAL,
        exit_price      REAL,
        quantity        INTEGER,
        stop_loss       REAL,
        target          REAL,
        analysis_id     INTEGER,
        notes           TEXT,
        created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (ticker) REFERENCES instruments(ticker),
        FOREIGN KEY (analysis_id) REFERENCES analyses(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)",
    "CREATE INDEX IF NOT EXISTS idx_trades_entry_date ON trades(entry_date)",
    # 7. scan_results — candidates surfaced by scripts/screen.py.
    # One row per (scan_date, ticker) that passed ALL three screening rules.
    # Research support only — these are candidates for manual review, never signals.
    """
    CREATE TABLE IF NOT EXISTS scan_results (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_date          DATE NOT NULL,
        ticker             TEXT NOT NULL,
        latest_date        DATE NOT NULL,
        latest_close       REAL NOT NULL,
        breakout_kind      TEXT,            -- 'up' | 'down'
        nearest_level      REAL,            -- S/R level price closest to latest_close
        nearest_level_kind TEXT,            -- 'support' | 'resistance'
        daily_sma50        REAL,
        daily_sma200       REAL,
        weekly_sma20       REAL,
        weekly_sma50       REAL,
        created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(scan_date, ticker),
        FOREIGN KEY (ticker) REFERENCES instruments(ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_scan_results_scan_date ON scan_results(scan_date)",
    "CREATE INDEX IF NOT EXISTS idx_scan_results_ticker ON scan_results(ticker)",
    # 8. scan_log — one row per screener run (mirrors fetch_log for health monitoring).
    """
    CREATE TABLE IF NOT EXISTS scan_log (
        id                            INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at                        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        scan_date                     DATE NOT NULL,
        tickers_total                 INTEGER NOT NULL,
        tickers_scanned               INTEGER NOT NULL,
        candidates                    INTEGER NOT NULL,
        skipped_no_levels             INTEGER NOT NULL DEFAULT 0,
        skipped_insufficient_history  INTEGER NOT NULL DEFAULT 0,
        skipped_stale                 INTEGER NOT NULL DEFAULT 0,
        errors                        INTEGER NOT NULL DEFAULT 0,
        obsidian_status               TEXT,    -- 'saved' | 'failed' | 'skipped'
        obsidian_message              TEXT,
        status                        TEXT NOT NULL,  -- 'success' | 'partial' | 'failed'
        duration_seconds              REAL
    )
    """,
    # 9. support_resistance — manually-curated S/R levels (NOT auto-detected).
    # The screener reads only from here; a ticker with no active rows is skipped.
    # S/R is a zone (methodology.md §4.3): level_high NULL means a single-price level.
    """
    CREATE TABLE IF NOT EXISTS support_resistance (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker      TEXT NOT NULL,
        timeframe   TEXT NOT NULL DEFAULT 'daily',   -- 'daily' | 'weekly' | 'monthly'
        kind        TEXT NOT NULL,                   -- 'support' | 'resistance'
        level_low   REAL NOT NULL,                   -- zone lower bound (or the price)
        level_high  REAL,                            -- zone upper bound; NULL = single price
        note        TEXT,                            -- why this level (e.g. "3rd touch")
        is_active   INTEGER NOT NULL DEFAULT 1,
        created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(ticker, timeframe, kind, level_low),
        FOREIGN KEY (ticker) REFERENCES instruments(ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sr_ticker_active ON support_resistance(ticker, is_active)",
]

# Idempotent column migrations for tables that may already exist (CREATE TABLE
# IF NOT EXISTS will not alter an existing table). Each entry: (table, column, decl).
COLUMN_MIGRATIONS = [
    ("scan_log", "skipped_stale", "INTEGER NOT NULL DEFAULT 0"),
]


def init_db(db_path: Path) -> None:
    """Create the Phase 3 tables (idempotent) and print a summary."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. "
            "Expected the existing analyses.db created by storage.py."
        )

    conn = sqlite3.connect(db_path)
    try:
        # Honor declared foreign keys for this connection.
        conn.execute("PRAGMA foreign_keys = ON")
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        for table, column, decl in COLUMN_MIGRATIONS:
            _ensure_column(conn, table, column, decl)
        init_indicator_snapshots(conn)
        conn.commit()
        _print_summary(conn, db_path)
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Add ``column`` to ``table`` if it is not already present (idempotent)."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_indicator_snapshots(conn: sqlite3.Connection) -> None:
    """Create the ``indicator_snapshots`` table for Phase 5b (idempotent).

    One row per (ticker, analysis_date): the latest computed indicator values
    across Monthly / Weekly / Daily timeframes, written by scripts/analyze.py.
    H1 is intentionally absent — there is no ohlcv_1h feed yet (phase3-schema.md
    "Deferred"). SMA pairs and RSI thresholds are per-instrument empirical
    (methodology.md §15.2, §15.3); the ``*_calibrated`` flags record whether a
    stored snapshot was produced against calibrated levels (default 0 = not yet).

    Research support only — raw indicator values, never signals or predictions.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS indicator_snapshots (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker              TEXT NOT NULL,
            analysis_date       DATE NOT NULL,
            latest_close        REAL,
            latest_date         DATE,
            daily_sma50         REAL,
            daily_sma200        REAL,
            daily_rsi14         REAL,
            daily_macd          REAL,
            daily_macd_signal   REAL,
            daily_macd_hist     REAL,
            daily_bb_upper      REAL,
            daily_bb_mid        REAL,
            daily_bb_lower      REAL,
            weekly_sma20        REAL,
            weekly_sma50        REAL,
            weekly_rsi14        REAL,
            weekly_macd         REAL,
            weekly_macd_signal  REAL,
            weekly_macd_hist    REAL,
            weekly_bb_upper     REAL,
            weekly_bb_mid       REAL,
            weekly_bb_lower     REAL,
            monthly_sma20       REAL,
            monthly_rsi14       REAL,
            monthly_macd        REAL,
            monthly_macd_signal REAL,
            monthly_macd_hist   REAL,
            monthly_bb_upper    REAL,
            monthly_bb_mid      REAL,
            monthly_bb_lower    REAL,
            vol_daily           INTEGER,
            vol_sma_20          REAL,
            vol_ratio           REAL,
            sma_pair_calibrated INTEGER DEFAULT 0,
            rsi_calibrated      INTEGER DEFAULT 0,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, analysis_date)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_indicator_snapshots_ticker ON indicator_snapshots(ticker)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_indicator_snapshots_date "
        "ON indicator_snapshots(analysis_date)"
    )


def _print_summary(conn: sqlite3.Connection, db_path: Path) -> None:
    """Print every user table now in the DB with its row count."""
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()

    print(f"\nDatabase: {db_path}")
    print(f"Tables ({len(rows)}):")
    print("-" * 40)
    for (name,) in rows:
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name:<18} {count:>8} rows")
    print("-" * 40)
    print("Phase 3 schema initialization complete.")


if __name__ == "__main__":
    init_db(DB_PATH)
