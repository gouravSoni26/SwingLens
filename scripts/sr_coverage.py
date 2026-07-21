"""Support/resistance curation cockpit for the NSE screener.

The screener (scripts/screen.py) only considers a ticker if it has at least one
active row in the manually-curated ``support_resistance`` table. Every other
active instrument is classified ``no_levels`` and skipped, so the screenable
universe is exactly the set of curated tickers. When most of the 500 names are
un-curated, zero-candidate days are the norm and no briefs get generated.

This script answers two questions and helps close the gap:

    1. Coverage — how many active tickers have levels, how many are missing.
    2. What next — emit a ready-to-fill CSV scaffold (``--todo``) listing the
       missing tickers with the seeder's exact columns, so you fill in your own
       zones and load them with scripts/seed_support_resistance.py.

Manual-only, always. This tool NEVER invents or suggests S/R levels — the
``kind``/``level_low``/``level_high`` cells are left blank for you. The optional
``ref_*`` columns are raw OHLCV facts (latest close, recent high/low) you would
read off a chart anyway; the seeder ignores them. Curating the actual zones from
your own chart analysis stays 100% manual (CLAUDE.md: methodology is manual).

Schema source of truth: docs/phase3-schema.md + scripts/init_db.py
Usage:
    python scripts/sr_coverage.py                 # print the coverage report
    python scripts/sr_coverage.py --todo          # + write data/sr_todo.csv
    python scripts/sr_coverage.py --todo levels_todo.csv   # custom output path

Stdlib only (csv, sqlite3, argparse, pathlib) — mirrors seed_support_resistance.
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "analyses.db"
DEFAULT_TODO_CSV = DATA_DIR / "sr_todo.csv"

# ~1 trading year of sessions — the window used only for the ref_high/ref_low
# helper columns (chart context, not a computed level).
REF_LOOKBACK_SESSIONS = 250

# The seeder's columns come FIRST so a filled TODO file loads directly via
# scripts/seed_support_resistance.py (it reads these by name, ignores the rest).
# The ref_* columns are appended as read-only charting context.
SEEDER_COLUMNS = ["ticker", "kind", "level_low", "timeframe", "level_high", "note"]
REF_COLUMNS = ["ref_latest_date", "ref_latest_close", "ref_high_250d", "ref_low_250d"]
TODO_HEADER = SEEDER_COLUMNS + REF_COLUMNS


def active_tickers(conn: sqlite3.Connection) -> list[str]:
    """Active instruments, mirroring screen.get_active_tickers exactly."""
    rows = conn.execute(
        "SELECT ticker FROM instruments WHERE is_active = 1 ORDER BY ticker"
    ).fetchall()
    return [r[0] for r in rows]


def tickers_with_levels(conn: sqlite3.Connection) -> set[str]:
    """Tickers the screener would actually use — those with an ACTIVE S/R row.

    Matches screen.screen_ticker's ``WHERE ticker = ? AND is_active = 1`` filter,
    so 'has levels' here means the same thing the screener means by it.
    """
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM support_resistance WHERE is_active = 1"
    ).fetchall()
    return {r[0] for r in rows}


def _round2(value: object) -> str:
    """Render a price to 2 decimals for the CSV; None/absent becomes ''."""
    return "" if value is None else f"{float(value):.2f}"


def reference_context(conn: sqlite3.Connection, ticker: str) -> dict[str, str]:
    """Latest close/date and recent high/low for one ticker from ohlcv_daily.

    Returns blanks (never raises) when a ticker has no price history yet, so the
    scaffold still lists it — the missing ref just means 'no OHLCV loaded'.
    """
    latest = conn.execute(
        "SELECT date, close FROM ohlcv_daily WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    hi_lo = conn.execute(
        """
        SELECT MAX(high), MIN(low) FROM (
            SELECT high, low FROM ohlcv_daily
            WHERE ticker = ? ORDER BY date DESC LIMIT ?
        )
        """,
        (ticker, REF_LOOKBACK_SESSIONS),
    ).fetchone()
    return {
        "ref_latest_date": (latest[0] if latest else ""),
        "ref_latest_close": _round2(latest[1] if latest else None),
        "ref_high_250d": _round2(hi_lo[0] if hi_lo else None),
        "ref_low_250d": _round2(hi_lo[1] if hi_lo else None),
    }


def print_report(active: list[str], curated: set[str]) -> list[str]:
    """Print the coverage summary and return the sorted list of missing tickers."""
    missing = sorted(t for t in active if t not in curated)
    have = len(active) - len(missing)
    pct = (have / len(active) * 100) if active else 0.0
    print("S/R coverage")
    print("=" * 40)
    print(f"Active tickers      : {len(active)}")
    print(f"  with levels       : {have}  ({pct:.1f}%)  <- screenable universe")
    print(f"  MISSING levels    : {len(missing)}  <- skipped as 'no_levels' every scan")
    print()
    if missing:
        preview = ", ".join(missing[:10])
        more = f"  (+{len(missing) - 10} more)" if len(missing) > 10 else ""
        print(f"First missing       : {preview}{more}")
    return missing


def write_todo_csv(conn: sqlite3.Connection, missing: list[str], out_path: Path) -> int:
    """Write a seeder-compatible scaffold for the missing tickers. Returns count.

    Each row pre-fills ``ticker`` and the ref_* charting context; the
    kind/level_low/level_high/timeframe/note cells stay blank for manual entry.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TODO_HEADER)
        writer.writeheader()
        for ticker in missing:
            row = {col: "" for col in TODO_HEADER}
            row["ticker"] = ticker
            row.update(reference_context(conn, ticker))
            writer.writerow(row)
    return len(missing)


def run(db_path: Path, todo_path: Path | None) -> None:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}. Run scripts/init_db.py first.")

    conn = sqlite3.connect(db_path)
    try:
        active = active_tickers(conn)
        curated = tickers_with_levels(conn)
        missing = print_report(active, curated)

        if todo_path is not None:
            count = write_todo_csv(conn, missing, todo_path)
            print()
            print(f"Wrote scaffold      : {todo_path}  ({count} ticker rows)")
            print("Next: fill kind/level_low[/level_high] from your chart analysis, then:")
            print(f"      python scripts/seed_support_resistance.py {todo_path}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report S/R coverage and scaffold a curation TODO CSV (manual levels only)."
    )
    parser.add_argument(
        "--todo",
        nargs="?",
        const=str(DEFAULT_TODO_CSV),
        default=None,
        help=f"Write a fill-in scaffold for the missing tickers (default: {DEFAULT_TODO_CSV}).",
    )
    args = parser.parse_args()
    todo_path = Path(args.todo) if args.todo is not None else None
    run(DB_PATH, todo_path)


if __name__ == "__main__":
    sys.exit(main())
