---
name: news-feed-fetcher
description: Fetches, parses, deduplicates, and formats RSS news feeds for Indian equity market context in the SwingLens project. Use this skill whenever you need to fetch news for a ticker or sector before building a Groq brief, whenever brief.py needs a news context block, whenever someone asks to "get news for X stock", or when constructing any LLM prompt that needs fresh Indian market headlines. Always use sector-news-router skill first to get the correct feed URLs, then use this skill to fetch and format them. This skill handles all RSS fetching logic — never write ad-hoc feed fetching code in SwingLens without consulting this skill.
---

# News Feed Fetcher

Fetches RSS feeds for Indian equity market context and formats them for injection into Groq briefs.

## Dependencies

```
feedparser>=6.0.0      # RSS parsing — add to requirements.txt if not present
requests>=2.28.0       # HTTP fetching (already in SwingLens requirements)
```

Install if missing:
```bash
pip install feedparser
```

---

## Workflow

1. Get feed URLs from `sector-news-router` skill (always do this first)
2. Call `fetch_news_context()` from `scripts/fetch_feeds.py`
3. Pass the returned string directly into the Groq prompt as `{news_context}`
4. Never pass raw feed XML/JSON to Groq — always use the formatted string output

---

## Core Script

The canonical fetcher lives at:
```
D:\nse-trading-analyst\scripts\fetch_feeds.py
```

Read `scripts/fetch_feeds.py` in this skill folder for the full implementation.

Key function signature:
```python
fetch_news_context(
    feed_urls: list[str],
    ticker: str,
    max_items_per_feed: int = 3,
    max_age_hours: int = 24,
    timeout_seconds: int = 8
) -> str
```

Returns a formatted string ready for Groq prompt injection.

---

## How to add to brief.py

Find the existing Groq prompt block in `brief.py` and add the news context block **before** the technical snapshot:

```python
# brief.py — add near top of file
from scripts.fetch_feeds import fetch_news_context

# Inside the brief generation function, before building the prompt:
from scripts.sector_router import get_feeds_for_ticker  # see sector-news-router skill

feed_urls = get_feeds_for_ticker(ticker)
news_context = fetch_news_context(
    feed_urls=feed_urls,
    ticker=ticker,
    max_items_per_feed=3,
    max_age_hours=24
)

# Then in the Groq prompt string:
prompt = f"""
## Macro & News Context (last 24 hours)
{news_context}

## Technical Snapshot
RSI: {rsi}
MACD: {macd_line} / Signal: {macd_signal}
...
"""
```

---

## Output Format

`fetch_news_context()` returns a plain string like this:

```
[Reuters India] RBI holds repo rate at 6.5%, signals data-dependent stance (2h ago)
[Economic Times] Nifty Bank outperforms as credit growth remains strong (4h ago)
[Business Standard] HDFC Bank Q1 results: Net profit up 18% YoY (6h ago)
[Moneycontrol] FII net buyers at ₹2,340 Cr; DII net sellers (8h ago)
[Economic Times] Crude oil falls to $82 on demand concerns (10h ago)
```

Format: `[Source] Headline (age ago)` — one line per item, sorted newest first.

If no news fetched (all feeds failed): returns `"No recent news available — technical analysis only."`

---

## Behaviour Rules

**Timeout:** Each feed gets `timeout_seconds` (default 8s). If it times out, skip silently — never crash `brief.py` because a feed is down.

**Deduplication:** Same headline from two sources = keep only the first occurrence (compare lowercased title, first 60 chars).

**Max age:** Items older than `max_age_hours` are dropped. Default 24h — keeps briefs relevant for swing trading timeframe.

**Max items per feed:** Default 3 — prevents any single source dominating the context block.

**Total cap:** Hard cap of 15 headlines total regardless of how many feeds are passed. Groq context window budget.

**Feed failures:** Log failed URLs to stderr with `[FEED WARN]` prefix. Never raise exceptions — brief.py must always complete.

**Encoding:** Force UTF-8 decode on all feed content. Indian news sources sometimes send latin-1 encoded responses.

---

## Error Handling Pattern

```python
try:
    news_context = fetch_news_context(feed_urls, ticker)
except Exception as e:
    # Should never reach here — fetch_news_context handles internally
    # but if it does, degrade gracefully
    news_context = "News context unavailable."
    print(f"[FEED ERROR] Unexpected: {e}")
```

---

## Testing

Run the standalone test:
```bash
cd D:\nse-trading-analyst
python scripts\fetch_feeds.py --ticker HDFCBANK --test
```

Expected output: 5–15 headlines, formatted, no errors.

If a feed returns 0 items in test mode, check:
1. Feed URL still valid (paste in browser)
2. `max_age_hours` not too tight
3. Network connectivity

---

## Governance Reminder

News context is **research input only**. The Groq prompt must never be structured to ask "should I buy/sell based on this news." News informs the brief narrative — it does not generate signals. See `success-criteria.md` governance doc.

---

## Reference files

- `scripts/fetch_feeds.py` — full Python implementation, copy to `D:\nse-trading-analyst\scripts\`
- `references/feed-troubleshooting.md` — common feed failures and fixes
