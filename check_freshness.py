#!/usr/bin/env python3
"""
SwingLens cloud freshness sentinel (v1, weekdays-only).
Runs on GitHub Actions. Downloads the pushed analyses.db from the
data-latest release, checks whether the newest analysis_date matches
the most recent expected trading day, and fires a Telegram alert if stale.
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

    # 2. Read the newest analysis_date inside it.
    conn = sqlite3.connect(DB_LOCAL_PATH)
    row = conn.execute("SELECT MAX(analysis_date) FROM analyses").fetchone()
    conn.close()
    newest = row[0]  # e.g. "2026-07-13", or None if table empty

    expected = most_recent_expected_trading_day(now_ist).isoformat()

    # 3. Decide. String compare is safe because format is YYYY-MM-DD.
    if newest is None or newest < expected:
    #if True:  # TEMP fire-drill: force the alert to test Telegram path
        msg = (
            "⚠️ SwingLens sentinel: cloud data looks STALE.\n"
            f"Newest analysis_date = {newest}\n"
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