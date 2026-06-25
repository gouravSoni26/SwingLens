"""Bulk-seed the instruments table from the Nifty 500 CSV.

Reads the NSE Nifty 500 constituents file and inserts every EQ-series row into
the ``instruments`` table with INSERT OR IGNORE, so re-running never duplicates
rows already present (e.g. the 5 test tickers from seed_instruments.py).

Column mapping (CSV -> instruments):
    Symbol        -> ticker  (Symbol + ".NS")
    Company Name  -> name
    Industry      -> sector
    (constant)    -> is_active = 1
Only rows where Series == 'EQ' are loaded.

Schema source of truth: docs/phase3-schema.md  (instruments table)
Usage:
    python scripts/seed_nifty500.py
    python scripts/seed_nifty500.py path/to/other.csv

Stdlib only (csv, sqlite3, pathlib).
"""

import csv
import sqlite3
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "analyses.db"
# Actual NSE export filename (the prompt referred to it as nifty500.csv).
DEFAULT_CSV = DATA_DIR / "ind_nifty500list.csv"

REQUIRED_COLUMNS = {"Company Name", "Industry", "Symbol", "Series", "ISIN Code"}


def load_eq_rows(csv_path: Path) -> list[tuple]:
    """Return [(ticker, name, sector, is_active), ...] for EQ-series rows."""
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{csv_path} is missing expected columns: {sorted(missing)}"
            )

        rows: list[tuple] = []
        for record in reader:
            if (record.get("Series") or "").strip().upper() != "EQ":
                continue
            symbol = (record.get("Symbol") or "").strip()
            name = (record.get("Company Name") or "").strip()
            sector = (record.get("Industry") or "").strip()
            if not symbol:
                continue
            rows.append((f"{symbol}.NS", name, sector, 1))
    return rows


def seed(db_path: Path, csv_path: Path) -> None:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found at {csv_path}.")
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run scripts/init_db.py first."
        )

    eq_rows = load_eq_rows(csv_path)

    conn = sqlite3.connect(db_path)
    try:
        before = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        conn.executemany(
            """
            INSERT OR IGNORE INTO instruments (ticker, name, sector, is_active)
            VALUES (?, ?, ?, ?)
            """,
            eq_rows,
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
    finally:
        conn.close()

    inserted = after - before
    skipped = len(eq_rows) - inserted

    print(f"Source CSV : {csv_path}")
    print(f"EQ rows read: {len(eq_rows)}")
    print(f"  inserted  : {inserted}")
    print(f"  skipped   : {skipped}  (already present)")
    print(f"instruments total now: {after}")


if __name__ == "__main__":
    csv_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    seed(DB_PATH, csv_arg)
