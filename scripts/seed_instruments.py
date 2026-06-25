"""Seed the instruments table with a small test universe.

Inserts 5 large-cap NSE tickers so the OHLCV fetcher has something to read
before the full Nifty 500 load is wired up. Uses INSERT OR IGNORE keyed on the
UNIQUE ticker column, so re-running never duplicates or overwrites rows.

Schema source of truth: docs/phase3-schema.md  (instruments table)
Usage:  python scripts/seed_instruments.py

Stdlib only (sqlite3, pathlib).
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "analyses.db"

# (ticker, name, sector) — 5 test tickers covering 3 sectors.
SEED_INSTRUMENTS = [
    ("RELIANCE.NS", "Reliance Industries Ltd", "Energy"),
    ("TCS.NS", "Tata Consultancy Services Ltd", "Information Technology"),
    ("INFY.NS", "Infosys Ltd", "Information Technology"),
    ("HDFCBANK.NS", "HDFC Bank Ltd", "Financial Services"),
    ("ICICIBANK.NS", "ICICI Bank Ltd", "Financial Services"),
]


def seed(db_path: Path) -> None:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run scripts/init_db.py first."
        )

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.executemany(
            "INSERT OR IGNORE INTO instruments (ticker, name, sector) VALUES (?, ?, ?)",
            SEED_INSTRUMENTS,
        )
        conn.commit()
        inserted = cur.rowcount  # rows actually inserted (ignored rows excluded)
        total = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]

        print(f"Seeded instruments into {db_path}")
        print(f"  newly inserted : {inserted}")
        print(f"  already present: {len(SEED_INSTRUMENTS) - inserted}")
        print(f"  total in table : {total}")
        print("-" * 40)
        for ticker, name, sector in conn.execute(
            "SELECT ticker, name, sector FROM instruments ORDER BY ticker"
        ):
            print(f"  {ticker:<14} {sector:<22} {name}")
    finally:
        conn.close()


if __name__ == "__main__":
    seed(DB_PATH)
