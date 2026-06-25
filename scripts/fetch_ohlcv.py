"""yfinance OHLCV fetcher for the NSE Trading Analyst pipeline.

Reads active tickers from the ``instruments`` table and pulls Daily / Weekly /
Monthly candles from yfinance into the matching ``ohlcv_*`` tables. Every batch
is logged to ``fetch_log`` so a failed bulk load can resume where it left off.

Behaviour
---------
- Timeframes:  daily (period=2y, 1d), weekly (period=8y, 1wk), monthly (max, 1mo)
- close column stores the ADJUSTED close (yfinance auto_adjust=True)
- INSERT OR REPLACE keyed on UNIQUE(ticker, date) — no duplicates
- Batches of 50 tickers; resume skips batches already logged 'success'
- One fetch_log row per (timeframe, batch) with success/fail counts + duration
- Progress is printed to the console for manual runs

Schema source of truth: docs/phase3-schema.md
Usage:
    python scripts/fetch_ohlcv.py
    python scripts/fetch_ohlcv.py --run-type daily_update
    python scripts/fetch_ohlcv.py --resume          # skip completed batches

yfinance is the only third-party dependency; everything else is stdlib.
"""

import argparse
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "analyses.db"

BATCH_SIZE = 50

# timeframe -> (yfinance period, yfinance interval, target table)
TIMEFRAMES = {
    "daily": ("2y", "1d", "ohlcv_daily"),
    "weekly": ("8y", "1wk", "ohlcv_weekly"),
    "monthly": ("max", "1mo", "ohlcv_monthly"),
}


def get_active_tickers(conn: sqlite3.Connection) -> list[str]:
    """Active tickers in a stable order so batch boundaries are deterministic."""
    rows = conn.execute(
        "SELECT ticker FROM instruments WHERE is_active = 1 ORDER BY ticker"
    ).fetchall()
    return [r[0] for r in rows]


def chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def completed_batches(conn: sqlite3.Connection, run_type: str, timeframe: str) -> set[int]:
    """Batch numbers already logged as fully 'success' for this run/timeframe."""
    rows = conn.execute(
        """
        SELECT batch_number FROM fetch_log
        WHERE run_type = ? AND timeframe = ? AND status = 'success'
              AND batch_number IS NOT NULL
        """,
        (run_type, timeframe),
    ).fetchall()
    return {r[0] for r in rows}


def fetch_ticker(ticker: str, period: str, interval: str) -> list[tuple]:
    """Return [(date_str, open, high, low, close, volume), ...] for one ticker.

    Uses auto_adjust=True so the Close column is already the adjusted close.
    Rows with NaN OHLC values are skipped; NaN volume becomes 0.
    """
    df = yf.Ticker(ticker).history(
        period=period, interval=interval, auto_adjust=True
    )
    rows: list[tuple] = []
    if df is None or df.empty:
        return rows

    for idx, row in df.iterrows():
        o, h, low, c = row.get("Open"), row.get("High"), row.get("Low"), row.get("Close")
        if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (o, h, low, c)):
            continue
        vol = row.get("Volume")
        vol = 0 if vol is None or (isinstance(vol, float) and math.isnan(vol)) else int(vol)
        rows.append((idx.strftime("%Y-%m-%d"), float(o), float(h), float(low), float(c), vol))
    return rows


def store_rows(conn: sqlite3.Connection, table: str, ticker: str, rows: list[tuple]) -> None:
    conn.executemany(
        f"""
        INSERT OR REPLACE INTO {table}
            (ticker, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(ticker, *r) for r in rows],
    )


def log_run(
    conn: sqlite3.Connection,
    *,
    run_type: str,
    timeframe: str,
    batch_number: int,
    total: int,
    success: int,
    failed_tickers: list[str],
    status: str,
    error_message: str | None,
    duration_seconds: float,
) -> None:
    conn.execute(
        """
        INSERT INTO fetch_log
            (run_type, timeframe, batch_number, tickers_total, tickers_success,
             tickers_failed, failed_tickers, status, error_message, duration_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_type,
            timeframe,
            batch_number,
            total,
            success,
            len(failed_tickers),
            json.dumps(failed_tickers),
            status,
            error_message,
            round(duration_seconds, 2),
        ),
    )
    conn.commit()


def process_batch(
    conn: sqlite3.Connection,
    *,
    run_type: str,
    timeframe: str,
    batch_number: int,
    tickers: list[str],
) -> tuple[int, list[str]]:
    """Fetch + store one batch for one timeframe. Returns (success, failed)."""
    period, interval, table = TIMEFRAMES[timeframe]
    start = time.monotonic()
    success = 0
    failed: list[str] = []

    for ticker in tickers:
        try:
            rows = fetch_ticker(ticker, period, interval)
            if not rows:
                failed.append(ticker)
                print(f"    {ticker:<14} no data returned")
                continue
            store_rows(conn, table, ticker, rows)
            conn.commit()
            success += 1
            print(f"    {ticker:<14} {len(rows):>5} rows")
        except Exception as exc:  # noqa: BLE001 — log per-ticker, never abort the batch
            failed.append(ticker)
            print(f"    {ticker:<14} ERROR: {exc}")

    duration = time.monotonic() - start
    if failed and success:
        status = "partial"
    elif failed:
        status = "failed"
    else:
        status = "success"

    log_run(
        conn,
        run_type=run_type,
        timeframe=timeframe,
        batch_number=batch_number,
        total=len(tickers),
        success=success,
        failed_tickers=failed,
        status=status,
        error_message=None,
        duration_seconds=duration,
    )
    print(
        f"  batch {batch_number} [{timeframe}] -> {status}: "
        f"{success}/{len(tickers)} ok, {len(failed)} failed, {duration:.1f}s"
    )
    return success, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch OHLCV data via yfinance.")
    parser.add_argument(
        "--run-type",
        default="initial_bulk",
        choices=["initial_bulk", "daily_update"],
        help="Logged to fetch_log.run_type (default: initial_bulk).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip (timeframe, batch) pairs already logged 'success'.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=BATCH_SIZE, help="Tickers per batch."
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found at {DB_PATH}. Run scripts/init_db.py first."
        )

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        tickers = get_active_tickers(conn)
        if not tickers:
            print("No active tickers in instruments. Run scripts/seed_instruments.py first.")
            return

        batches = chunk(tickers, args.batch_size)
        started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"Fetch started {started}")
        print(f"Run type: {args.run_type} | active tickers: {len(tickers)} | batches: {len(batches)}")

        grand_success = 0
        grand_failed: list[str] = []

        for timeframe in TIMEFRAMES:
            done = completed_batches(conn, args.run_type, timeframe) if args.resume else set()
            print(f"\n=== {timeframe.upper()} ===")
            for i, batch in enumerate(batches, start=1):
                if i in done:
                    print(f"  batch {i} [{timeframe}] -> skipped (already success)")
                    continue
                print(f"  batch {i}/{len(batches)} [{timeframe}] ({len(batch)} tickers)")
                success, failed = process_batch(
                    conn,
                    run_type=args.run_type,
                    timeframe=timeframe,
                    batch_number=i,
                    tickers=batch,
                )
                grand_success += success
                grand_failed.extend(f"{timeframe}:{t}" for t in failed)

        print("\n" + "=" * 40)
        print(f"Done. ticker-timeframe successes: {grand_success}, failures: {len(grand_failed)}")
        if grand_failed:
            print(f"Failed: {grand_failed}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
