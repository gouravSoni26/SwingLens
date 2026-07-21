#!/usr/bin/env python3
"""
SwingLens cloud freshness sentinel (v2, weekdays-only).
Runs on GitHub Actions. Downloads the pushed analyses.db from the
data-latest release, checks whether the pipeline actually RAN for the
most recent expected trading day, and fires a Telegram alert if stale.

Liveness signal — why scan_log, not analyses:
    v1 read MAX(analysis_date) FROM analyses. That table is only written by
    brief.py, one row per *briefed candidate*. On a legitimate zero-candidate
    day the whole pipeline runs perfectly yet inserts no analyses row, so v1
    false-alarmed ("STALE") every day the screener found no setups.
    scan_log gets exactly one row per screen.py run (screen.log_run, every run,
    success or partial, candidates or not), so MAX(scan_date) there advances
    whenever the pipeline runs and only goes stale when a run is genuinely
    missed. That is the freshness question we actually want answered.
"""

import os
import sys
import sqlite3
import urllib.request
from datetime import datetime, timezone, timedelta

# --- Named constants (no magic numbers) ---
IST = timezone(timedelta(hours=5, minutes=30))   # India Standard Time
DB_ASSET_NAME = "analyses.db"                     # the asset we care about on the release
DB_LOCAL_PATH = "downloaded_analyses.db"          # where we save it on the runner
SATURDAY, SUNDAY = 5, 6                           # Python weekday() codes

# --- Secrets / config from environment (set by the workflow) ---
BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID     = os.environ["TELEGRAM_CHAT_ID"]
DB_URL      = os.environ["DB_ASSET_URL"]          # direct download URL for analyses.db


def send_telegram(text: str) -> None:
    """Fire a message to the configured chat via the bot."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
    with urllib.request.urlopen(url, data=data, timeout=30) as resp:
        resp.read()


def most_recent_expected_trading_day(now_ist: datetime):
    """
    Weekdays-only v1: the most recent completed trading day.
    At 9 AM IST the 6 AM pipeline should already have landed today's data,
    so on a weekday the expected newest date is today itself.
    On Sat/Sun we don't expect new data, so we look back to Friday.
    NOTE: this does NOT know NSE holidays -> will false-alarm on the
    ~12 market holidays/year. Accepted tradeoff for v1.
    """
    d = now_ist.date()
    wd = now_ist.weekday()
    if wd == SATURDAY:
        return d - timedelta(days=1)   # Friday
    if wd == SUNDAY:
        return d - timedelta(days=2)   # Friday
    return d                            # weekday -> expect today's run


def main() -> int:
    now_ist = datetime.now(IST)

    # 1. Download the pushed db from the release asset.
    urllib.request.urlretrieve(DB_URL, DB_LOCAL_PATH)

    # 2. Read the newest scan_date inside it. scan_log gets one row per screen
    #    run regardless of candidate count, so it tracks whether the pipeline
    #    RAN — unlike analyses, which only grows on candidate days (see module
    #    docstring). None means the table is empty/absent -> treat as stale.
    conn = sqlite3.connect(DB_LOCAL_PATH)
    row = conn.execute("SELECT MAX(scan_date) FROM scan_log").fetchone()
    conn.close()
    newest = row[0]  # e.g. "2026-07-21", or None if table empty

    expected = most_recent_expected_trading_day(now_ist).isoformat()

    # 3. Decide. String compare is safe because format is YYYY-MM-DD.
    if newest is None or newest < expected:
        msg = (
            "⚠️ SwingLens sentinel: cloud data looks STALE.\n"
            f"Newest scan_date = {newest}\n"
            f"Expected (>= last trading day) = {expected}\n"
            f"Checked at {now_ist.strftime('%Y-%m-%d %H:%M IST')}.\n"
            "The 6 AM pipeline may have missed a run or failed to push."
        )
        send_telegram(msg)
        print(f"STALE -> alert sent. newest={newest} expected={expected}")
        return 1

    print(f"FRESH -> no alert. newest={newest} expected={expected}")
    return 0


if __name__ == "__main__":
    # urllib.parse needed inside send_telegram; import here to keep top clean
    import urllib.parse
    sys.exit(main())