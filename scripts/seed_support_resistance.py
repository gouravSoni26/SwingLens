"""Bulk-load manually-curated support/resistance levels from a CSV.

The screener (scripts/screen.py) reads S/R levels ONLY from the
``support_resistance`` table — nothing is auto-detected. Curate levels from your
own chart analysis into a CSV, then load them here. Re-running is safe: a
UNIQUE(ticker, timeframe, kind, level_low) constraint means INSERT OR IGNORE
never duplicates a level already present.

CSV columns (header row required):
    ticker       e.g. RELIANCE.NS            (required)
    kind         'support' | 'resistance'    (required)
    level_low    zone lower bound / price    (required, float)
    timeframe    'daily'|'weekly'|'monthly'  (optional, default 'daily')
    level_high   zone upper bound            (optional; blank => single price)
    note         free text                   (optional)

Schema source of truth: docs/phase3-schema.md + scripts/init_db.py
Usage:
    python scripts/seed_support_resistance.py
    python scripts/seed_support_resistance.py path/to/levels.csv

Stdlib only (csv, sqlite3, pathlib).
"""

import csv
import sqlite3
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "analyses.db"
DEFAULT_CSV = DATA_DIR / "support_resistance.csv"

REQUIRED_COLUMNS = {"ticker", "kind", "level_low"}
VALID_KINDS = {"support", "resistance"}
VALID_TIMEFRAMES = {"daily", "weekly", "monthly"}


def _parse_float(value: str, field: str, line_no: int) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Row {line_no}: {field} is not a number: {value!r}") from e


def load_rows(csv_path: Path) -> list[tuple]:
    """Return [(ticker, timeframe, kind, level_low, level_high, note), ...]."""
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{csv_path} is missing required columns: {sorted(missing)}"
            )

        rows: list[tuple] = []
        for line_no, record in enumerate(reader, start=2):  # row 1 is the header
            ticker = (record.get("ticker") or "").strip()
            kind = (record.get("kind") or "").strip().lower()
            if not ticker:
                continue
            if kind not in VALID_KINDS:
                raise ValueError(
                    f"Row {line_no}: kind must be one of {sorted(VALID_KINDS)}, "
                    f"got {kind!r}"
                )

            timeframe = (record.get("timeframe") or "daily").strip().lower() or "daily"
            if timeframe not in VALID_TIMEFRAMES:
                raise ValueError(
                    f"Row {line_no}: timeframe must be one of "
                    f"{sorted(VALID_TIMEFRAMES)}, got {timeframe!r}"
                )

            level_low = _parse_float(record.get("level_low"), "level_low", line_no)
            high_raw = (record.get("level_high") or "").strip()
            level_high = _parse_float(high_raw, "level_high", line_no) if high_raw else None
            note = (record.get("note") or "").strip() or None

            rows.append((ticker, timeframe, kind, level_low, level_high, note))
    return rows


def seed(db_path: Path, csv_path: Path) -> None:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found at {csv_path}.")
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run scripts/init_db.py first."
        )

    rows = load_rows(csv_path)

    conn = sqlite3.connect(db_path)
    try:
        before = conn.execute("SELECT COUNT(*) FROM support_resistance").fetchone()[0]
        conn.executemany(
            """
            INSERT OR IGNORE INTO support_resistance
                (ticker, timeframe, kind, level_low, level_high, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM support_resistance").fetchone()[0]
    finally:
        conn.close()

    inserted = after - before
    skipped = len(rows) - inserted

    print(f"Source CSV : {csv_path}")
    print(f"Rows read  : {len(rows)}")
    print(f"  inserted : {inserted}")
    print(f"  skipped  : {skipped}  (already present)")
    print(f"support_resistance total now: {after}")


if __name__ == "__main__":
    csv_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    seed(DB_PATH, csv_arg)
