# Feed Troubleshooting Guide

Common issues when RSS feeds fail in SwingLens and how to fix them.

---

## Feed returns 0 items

**Check 1 — URL still valid?**
Paste the feed URL in a browser. If you see XML, the feed is live.
If you get a 404 or redirect, the URL has changed — update `sector-news-router` skill.

**Check 2 — max_age_hours too tight?**
If running `brief.py` on a weekend or public holiday, news volume drops.
Temporarily increase to `max_age_hours=48` and retest.

**Check 3 — All items have no publish date?**
Some feeds (especially Indian regional ones) omit `<pubDate>`.
`_parse_age()` returns 999 for these → they get filtered out.
Fix: set `max_age_hours=999` in test mode to see if items exist at all.

---

## Timeout errors

**Symptom:** `[FEED WARN] Timeout fetching https://...`

**Cause:** Indian news sites occasionally throttle or go slow during peak hours.

**Fix:** Increase `timeout_seconds=15` for that specific feed URL.
Or remove the feed temporarily and use an alternative from `sector-news-router`.

**Never:** Do not set timeout to 0 or None — this will hang `brief.py` indefinitely.

---

## Encoding errors / garbled text

**Symptom:** Headlines contain `â€™` or `Ã©` instead of proper characters.

**Cause:** Feed claims latin-1 encoding but serves UTF-8 (common with ET, MC).

**Fix:** Already handled in `fetch_feeds.py` with `response.encoding = "utf-8"`.
If still garbled, add explicit decode:
```python
raw_content = response.content.decode("utf-8", errors="replace")
```

---

## feedparser not installed

**Symptom:** `ModuleNotFoundError: No module named 'feedparser'`

**Fix:**
```bash
D:\Python314\python.exe -m pip install feedparser
```

Note: Use `D:\Python314\python.exe` — not `python` — to match SwingLens project Python path.

---

## Reuters feed blocked

**Symptom:** Reuters returns 403 or empty feed.

**Cause:** Reuters occasionally blocks automated fetchers.

**Fix:** Add a more descriptive User-Agent or use the ET/BS equivalent:
```
https://economictimes.indiatimes.com/markets/rss.cms
https://www.business-standard.com/rss/markets-106.rss
```

---

## RBI feed returns old content

**Symptom:** RBI RSS items are weeks old.

**Cause:** RBI only publishes RSS items when there is an official announcement.
Between MPC meetings, the feed is intentionally sparse.

**Fix:** This is expected behaviour. Do not raise `max_age_hours` — old RBI items are not relevant.
Note in the brief: "No recent RBI announcement."

---

## brief.py hangs on news fetch

**Symptom:** `brief.py` runs but never completes — stuck on feed fetching.

**Cause:** One feed is hanging without triggering a timeout (rare network edge case).

**Fix:** Add a global timeout wrapper around the entire `fetch_news_context()` call:
```python
import signal

def _timeout_handler(signum, frame):
    raise TimeoutError("News fetch exceeded global timeout")

signal.signal(signal.SIGALRM, _timeout_handler)
signal.alarm(60)  # 60 second global cap
try:
    news_context = fetch_news_context(feeds, ticker)
finally:
    signal.alarm(0)
```

Note: `signal.SIGALRM` is Unix only. On Windows, use `concurrent.futures.ThreadPoolExecutor` with a timeout instead.

---

## Windows-specific: signal.SIGALRM not available

**Symptom:** `AttributeError: module 'signal' has no attribute 'SIGALRM'`

**Cause:** SIGALRM is Unix-only. SwingLens runs on Windows.

**Fix:** Use ThreadPoolExecutor pattern instead:
```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(fetch_news_context, feeds, ticker)
    try:
        news_context = future.result(timeout=60)
    except FuturesTimeout:
        news_context = "News fetch timed out — technical analysis only."
```
