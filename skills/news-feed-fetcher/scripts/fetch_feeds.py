"""
fetch_feeds.py — News RSS fetcher for SwingLens brief.py
Part of: news-feed-fetcher skill

Copy this file to: D:\\nse-trading-analyst\\scripts\\fetch_feeds.py

Usage:
    from scripts.fetch_feeds import fetch_news_context
    news_context = fetch_news_context(feed_urls, ticker)

    # Standalone test:
    python scripts\\fetch_feeds.py --ticker HDFCBANK --test
"""

import sys
import hashlib
import argparse
from datetime import datetime, timezone, timedelta

import requests
import feedparser

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ITEMS_PER_FEED = 3
MAX_AGE_HOURS = 24
TIMEOUT_SECONDS = 8
TOTAL_HEADLINE_CAP = 15
DEDUP_TITLE_CHARS = 60  # compare first N chars for deduplication

# Source display name map — makes output readable
SOURCE_NAMES = {
    "feeds.reuters.com": "Reuters India",
    "economictimes.indiatimes.com": "Economic Times",
    "www.rbi.org.in": "RBI",
    "www.moneycontrol.com": "Moneycontrol",
    "www.business-standard.com": "Business Standard",
    "www.fda.gov": "US FDA",
    "www.livemint.com": "Mint",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_label(url: str) -> str:
    """Extract a readable source name from a feed URL."""
    for domain, label in SOURCE_NAMES.items():
        if domain in url:
            return label
    # Fallback: use domain portion
    try:
        return url.split("/")[2].replace("www.", "").split(".")[0].title()
    except Exception:
        return "News"


def _parse_age(entry) -> float:
    """Return age of entry in hours. Returns 999 if unparseable (will be filtered out)."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                import calendar
                pub_dt = datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
                age = (datetime.now(tz=timezone.utc) - pub_dt).total_seconds() / 3600
                return age
            except Exception:
                pass
    return 999.0  # unknown age — exclude


def _dedup_key(title: str) -> str:
    """Normalised key for deduplication."""
    return title.lower().strip()[:DEDUP_TITLE_CHARS]


def _age_label(hours: float) -> str:
    """Human-readable age string."""
    if hours < 1:
        return f"{int(hours * 60)}m ago"
    elif hours < 24:
        return f"{int(hours)}h ago"
    else:
        return f"{int(hours / 24)}d ago"


# ---------------------------------------------------------------------------
# Core fetcher
# ---------------------------------------------------------------------------

def fetch_news_context(
    feed_urls: list,
    ticker: str = "",
    max_items_per_feed: int = MAX_ITEMS_PER_FEED,
    max_age_hours: int = MAX_AGE_HOURS,
    timeout_seconds: int = TIMEOUT_SECONDS,
) -> str:
    """
    Fetch RSS feeds and return a formatted news context string for Groq prompt injection.

    Args:
        feed_urls:          List of RSS feed URLs (from sector-news-router skill)
        ticker:             NSE ticker symbol — used for logging only
        max_items_per_feed: Max headlines to take from each feed
        max_age_hours:      Drop items older than this
        timeout_seconds:    Per-feed HTTP timeout

    Returns:
        Formatted multi-line string ready for Groq prompt injection.
        Returns fallback string if all feeds fail — never raises.
    """
    headlines = []   # list of (age_hours, label, title)
    seen_keys = set()

    for url in feed_urls:
        try:
            # Fetch raw feed bytes with requests (better timeout control than feedparser)
            response = requests.get(
                url,
                timeout=timeout_seconds,
                headers={"User-Agent": "SwingLens/1.0 (RSS reader; contact: swinglens)"},
            )
            response.raise_for_status()

            # Force UTF-8 — Indian sources sometimes misreport encoding
            response.encoding = "utf-8"
            raw_content = response.text

            # Parse with feedparser
            feed = feedparser.parse(raw_content)
            source = _source_label(url)
            count = 0

            for entry in feed.entries:
                if count >= max_items_per_feed:
                    break

                title = getattr(entry, "title", "").strip()
                if not title:
                    continue

                age = _parse_age(entry)
                if age > max_age_hours:
                    continue

                key = _dedup_key(title)
                if key in seen_keys:
                    continue

                seen_keys.add(key)
                headlines.append((age, source, title))
                count += 1

        except requests.exceptions.Timeout:
            print(f"[FEED WARN] Timeout fetching {url} for {ticker}", file=sys.stderr)
        except requests.exceptions.RequestException as e:
            print(f"[FEED WARN] Failed {url} for {ticker}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[FEED WARN] Unexpected error {url} for {ticker}: {e}", file=sys.stderr)

    if not headlines:
        return "No recent news available — technical analysis only."

    # Sort by age (newest first) and cap total
    headlines.sort(key=lambda x: x[0])
    headlines = headlines[:TOTAL_HEADLINE_CAP]

    # Format output
    lines = []
    for age, source, title in headlines:
        lines.append(f"[{source}] {title} ({_age_label(age)})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone test mode
# ---------------------------------------------------------------------------

def _test_mode(ticker: str):
    """Quick smoke test — fetches universal Indian market feeds."""
    from scripts.sector_router import get_feeds_for_ticker  # noqa: F401

    UNIVERSAL_FEEDS = [
        "https://feeds.reuters.com/reuters/INbusinessNews",
        "https://economictimes.indiatimes.com/markets/rss.cms",
        "https://www.moneycontrol.com/rss/marketreports.xml",
        "https://www.business-standard.com/rss/markets-106.rss",
    ]

    print(f"\n=== SwingLens News Feed Test — {ticker} ===\n")

    try:
        # Try to use sector router if available
        feeds = get_feeds_for_ticker(ticker)
        print(f"Using sector-router feeds: {len(feeds)} URLs\n")
    except ImportError:
        feeds = UNIVERSAL_FEEDS
        print(f"sector_router not found — using {len(feeds)} universal feeds\n")

    result = fetch_news_context(feeds, ticker=ticker)
    print(result)
    print(f"\n--- {len(result.splitlines())} headlines fetched ---")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SwingLens RSS feed fetcher test")
    parser.add_argument("--ticker", default="NIFTY50", help="NSE ticker to test with")
    parser.add_argument("--test", action="store_true", help="Run in test mode")
    args = parser.parse_args()

    if args.test:
        _test_mode(args.ticker)
    else:
        print("Run with --test flag. Example:")
        print("  python scripts\\fetch_feeds.py --ticker HDFCBANK --test")
