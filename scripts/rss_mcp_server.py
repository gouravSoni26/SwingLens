"""
RSS MCP Server for SwingLens
============================
Exposes a single MCP tool: get_news_for_ticker(ticker)

Wraps the news-feed-fetcher + sector-news-router logic from the
SwingLens skills into a Claude Code-callable MCP server.

Usage (register with Claude Code):
    claude mcp add rss-news -- D:/nse-trading-analyst/trading-app/Scripts/python.exe \
        D:/nse-trading-analyst/scripts/rss_mcp_server.py

Or via claude_desktop_config.json:
    {
      "mcpServers": {
        "rss-news": {
          "command": "D:/nse-trading-analyst/trading-app/Scripts/python.exe",
          "args": ["D:/nse-trading-analyst/scripts/rss_mcp_server.py"]
        }
      }
    }
"""

import json
import sys
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Minimal MCP server implementation (no external mcp package required)
# Uses the MCP stdio JSON-RPC protocol directly
# ---------------------------------------------------------------------------

# ponytail: Windows stdio defaults to cp1252, which can't encode ₹ etc.
# Force UTF-8 on the JSON-RPC streams so non-Latin1 chars survive.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.WARNING,
    stream=sys.stderr,
    format="%(asctime)s [rss-mcp] %(levelname)s %(message)s",
)
logger = logging.getLogger("rss-mcp")


# ---------------------------------------------------------------------------
# Sector → Feed URL mapping  (from sector-news-router skill)
# ---------------------------------------------------------------------------

# Only confirmed-working feeds (probed 2026-06-29). ET, Business Standard,
# Moneycontrol, Reuters, RBI, FDA all blocked/dead from this host — removed.
UNIVERSAL_FEEDS = [
    "https://www.livemint.com/rss/markets",
    "https://www.livemint.com/rss/companies",
    "https://www.thehindubusinessline.com/markets/?service=rss",
    "https://www.thehindubusinessline.com/economy/?service=rss",
]

# IT gets dedicated tech feeds; every other sector shares the same
# industry + companies supplement (no working sector-specific feeds remain).
_SECTOR_SUPPLEMENT = [
    "https://www.livemint.com/rss/industry",
    "https://www.thehindubusinessline.com/companies/?service=rss",
]

_IT_FEEDS = [
    "https://www.livemint.com/rss/technology",
    "https://www.thehindubusinessline.com/info-tech/?service=rss",
]

SECTOR_FEEDS: dict[str, list[str]] = {
    "banking_finance": _SECTOR_SUPPLEMENT,
    "it_technology": _IT_FEEDS,
    "oil_gas_energy": _SECTOR_SUPPLEMENT,
    "pharma_healthcare": _SECTOR_SUPPLEMENT,
    "fmcg_consumer": _SECTOR_SUPPLEMENT,
    "auto": _SECTOR_SUPPLEMENT,
    "metals_mining": _SECTOR_SUPPLEMENT,
    "cement_infra": _SECTOR_SUPPLEMENT,
    "telecom": _SECTOR_SUPPLEMENT,
    "power_utilities": _SECTOR_SUPPLEMENT,
    "paint_chemicals": _SECTOR_SUPPLEMENT,
}

# Ticker → sector key  (strip .NS suffix before lookup)
TICKER_SECTOR: dict[str, str] = {
    # Banking & Finance
    "HDFCBANK": "banking_finance", "ICICIBANK": "banking_finance",
    "KOTAKBANK": "banking_finance", "AXISBANK": "banking_finance",
    "SBIN": "banking_finance", "BAJFINANCE": "banking_finance",
    "BAJAJFINSV": "banking_finance", "INDUSINDBK": "banking_finance",
    "BANDHANBNK": "banking_finance", "FEDERALBNK": "banking_finance",
    "IDFCFIRSTB": "banking_finance", "PNB": "banking_finance",
    "CANBK": "banking_finance", "BANKBARODA": "banking_finance",

    # IT & Technology
    "INFY": "it_technology", "TCS": "it_technology",
    "WIPRO": "it_technology", "HCLTECH": "it_technology",
    "TECHM": "it_technology", "LTIM": "it_technology",
    "MPHASIS": "it_technology", "PERSISTENT": "it_technology",
    "COFORGE": "it_technology", "OFSS": "it_technology",

    # Oil & Gas / Energy
    "RELIANCE": "oil_gas_energy", "ONGC": "oil_gas_energy",
    "BPCL": "oil_gas_energy", "IOC": "oil_gas_energy",
    "GAIL": "oil_gas_energy", "OIL": "oil_gas_energy",
    "MGL": "oil_gas_energy", "IGL": "oil_gas_energy",

    # Pharma & Healthcare
    "SUNPHARMA": "pharma_healthcare", "DRREDDY": "pharma_healthcare",
    "CIPLA": "pharma_healthcare", "DIVISLAB": "pharma_healthcare",
    "APOLLOHOSP": "pharma_healthcare", "BIOCON": "pharma_healthcare",
    "LUPIN": "pharma_healthcare", "AUROPHARMA": "pharma_healthcare",
    "TORNTPHARM": "pharma_healthcare", "ALKEM": "pharma_healthcare",

    # FMCG & Consumer
    "HINDUNILVR": "fmcg_consumer", "ITC": "fmcg_consumer",
    "NESTLEIND": "fmcg_consumer", "BRITANNIA": "fmcg_consumer",
    "MARICO": "fmcg_consumer", "DABUR": "fmcg_consumer",
    "GODREJCP": "fmcg_consumer", "COLPAL": "fmcg_consumer",
    "EMAMILTD": "fmcg_consumer", "VBL": "fmcg_consumer",

    # Auto & Auto Ancillary
    "MARUTI": "auto", "TATAMOTORS": "auto", "M&M": "auto",
    "BAJAJ-AUTO": "auto", "EICHERMOT": "auto", "HEROMOTOCO": "auto",
    "TVSMOTOR": "auto", "MOTHERSON": "auto", "BOSCHLTD": "auto",
    "BALKRISIND": "auto", "MRF": "auto", "APOLLOTYRE": "auto",

    # Metals & Mining
    "TATASTEEL": "metals_mining", "JSWSTEEL": "metals_mining",
    "HINDALCO": "metals_mining", "COALINDIA": "metals_mining",
    "VEDL": "metals_mining", "NMDC": "metals_mining",
    "SAIL": "metals_mining", "JINDALSTEL": "metals_mining",

    # Cement & Infrastructure
    "ULTRACEMCO": "cement_infra", "GRASIM": "cement_infra",
    "ADANIENT": "cement_infra", "ADANIPORTS": "cement_infra",
    "LT": "cement_infra", "AMBUJACEM": "cement_infra",
    "ACC": "cement_infra", "SHREECEM": "cement_infra",

    # Telecom
    "BHARTIARTL": "telecom", "IDEA": "telecom",

    # Power & Utilities
    "POWERGRID": "power_utilities", "NTPC": "power_utilities",
    "ADANIGREEN": "power_utilities", "TATAPOWER": "power_utilities",
    "CESC": "power_utilities",

    # Paint & Chemicals
    "ASIANPAINT": "paint_chemicals", "PIDILITIND": "paint_chemicals",
    "BERGER": "paint_chemicals", "KANSAINER": "paint_chemicals",
    "SRF": "paint_chemicals", "AAPL": "paint_chemicals",
}


def resolve_sector(ticker: str) -> str | None:
    """Return sector key for a ticker, stripping .NS suffix if present."""
    clean = ticker.upper().replace(".NS", "").strip()
    return TICKER_SECTOR.get(clean)


def get_feeds_for_ticker(ticker: str, max_feeds: int = 7) -> dict[str, Any]:
    """
    Return the feed URLs for a given ticker.
    Always includes 2-3 universal feeds + up to 2-3 sector-specific feeds.
    max_feeds: hard cap so Groq context stays manageable (skill says 5-7).
    """
    sector = resolve_sector(ticker)
    clean = ticker.upper().replace(".NS", "")

    # Pick 2 universal feeds (most signal-dense for Indian market)
    universal = UNIVERSAL_FEEDS[:2]

    if sector and sector in SECTOR_FEEDS:
        sector_specific = SECTOR_FEEDS[sector][:3]
        feeds = universal + sector_specific
    else:
        # Unknown sector — fall back to all universal feeds
        feeds = UNIVERSAL_FEEDS[:max_feeds]
        sector = None

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped = []
    for f in feeds:
        if f not in seen:
            seen.add(f)
            deduped.append(f)

    return {
        "ticker": clean,
        "sector": sector or "unknown",
        "feeds": deduped[:max_feeds],
    }


# ---------------------------------------------------------------------------
# RSS fetch logic  (from news-feed-fetcher skill)
# ---------------------------------------------------------------------------

def fetch_and_parse_feeds(feed_urls: list[str], max_items_per_feed: int = 5) -> list[dict]:
    """
    Fetch and parse RSS feeds. Returns deduplicated list of items.
    Requires feedparser to be installed in the trading-app venv.
    """
    try:
        import feedparser  # type: ignore
    except ImportError:
        raise RuntimeError(
            "feedparser not installed. Run: "
            "D:/nse-trading-analyst/trading-app/Scripts/python.exe -m pip install feedparser"
        )

    items: list[dict] = []
    seen_titles: set[str] = set()

    # ET and Moneycontrol block the default feedparser UA — use a real Chrome UA
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    for url in feed_urls:
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            if feed.bozo and not feed.entries:
                logger.warning("Feed parse error for %s: %s", url, feed.bozo_exception)
                continue

            for entry in feed.entries[:max_items_per_feed]:
                title = (entry.get("title") or "").strip()
                if not title or title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())

                # Parse published date
                published = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        published = dt.strftime("%Y-%m-%d %H:%M UTC")
                    except Exception:
                        published = entry.get("published", "")
                else:
                    published = entry.get("published", "")

                items.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "published": published,
                    "summary": (entry.get("summary") or "")[:400].strip(),
                    "source": feed.feed.get("title", url),
                })

        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            continue

    return items


def format_news_block(ticker: str, items: list[dict], sector: str) -> str:
    """
    Format fetched news items into the canonical Groq prompt news block
    (as specified in the macro-context-injector skill).
    """
    if not items:
        return f"[NEWS CONTEXT: No items fetched for {ticker} ({sector}). Proceed with technical analysis only.]"

    lines = [
        f"=== NEWS CONTEXT: {ticker} ({sector.replace('_', ' ').title()}) ===",
        f"Fetched: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | Items: {len(items)}",
        "",
    ]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. [{item['published']}] {item['title']}")
        if item["summary"]:
            lines.append(f"   {item['summary'][:200]}")
        lines.append(f"   Source: {item['source']}")
        lines.append("")

    lines.append("=== END NEWS CONTEXT ===")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core tool handler
# ---------------------------------------------------------------------------

def handle_get_news_for_ticker(args: dict) -> str:
    """
    Main tool implementation.
    Args:
        ticker: NSE ticker symbol e.g. "INFY.NS" or "INFY"
        max_items_per_feed: optional, default 5
        max_feeds: optional, default 7
        format: "text" (default for Groq prompt block) | "json" (raw list)
    Returns:
        Formatted news block string (or JSON)
    """
    ticker = args.get("ticker", "").strip()
    if not ticker:
        return "[ERROR: ticker parameter is required]"

    max_items_per_feed = int(args.get("max_items_per_feed", 5))
    max_feeds = int(args.get("max_feeds", 7))
    output_format = args.get("format", "text")

    # Resolve feeds
    feed_info = get_feeds_for_ticker(ticker, max_feeds=max_feeds)

    # Fetch news
    items = fetch_and_parse_feeds(feed_info["feeds"], max_items_per_feed=max_items_per_feed)

    if output_format == "json":
        return json.dumps({
            "ticker": feed_info["ticker"],
            "sector": feed_info["sector"],
            "feeds_used": feed_info["feeds"],
            "item_count": len(items),
            "items": items,
        }, ensure_ascii=False, indent=2)

    # Default: Groq-ready text block
    return format_news_block(feed_info["ticker"], items, feed_info["sector"])


def handle_list_sectors(_args: dict) -> str:
    """Helper tool: show all known sectors and sample tickers."""
    result = {"sectors": {}}
    sector_to_tickers: dict[str, list[str]] = {}
    for ticker, sector in TICKER_SECTOR.items():
        sector_to_tickers.setdefault(sector, []).append(ticker)
    for sector, tickers in sector_to_tickers.items():
        result["sectors"][sector] = {
            "feed_count": len(SECTOR_FEEDS.get(sector, [])),
            "sample_tickers": tickers[:5],
        }
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# MCP stdio JSON-RPC server (no external mcp package needed)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "get_news_for_ticker",
        "description": (
            "Fetch recent RSS news headlines for an NSE ticker. "
            "Automatically routes to the correct sector feeds (banking, IT, pharma, etc.) "
            "plus universal Indian market feeds. Returns a formatted news context block "
            "ready to inject into a Groq brief prompt. "
            "Use this before generating any SwingLens daily brief."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "NSE ticker symbol e.g. 'INFY.NS' or 'INFY' or 'HDFCBANK'",
                },
                "max_items_per_feed": {
                    "type": "integer",
                    "description": "Max news items per RSS feed (default: 5)",
                    "default": 5,
                },
                "max_feeds": {
                    "type": "integer",
                    "description": "Max feeds to query (default: 7, max recommended: 7)",
                    "default": 7,
                },
                "format": {
                    "type": "string",
                    "enum": ["text", "json"],
                    "description": "'text' returns a Groq-ready prompt block. 'json' returns raw structured data.",
                    "default": "text",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "list_sectors",
        "description": (
            "List all supported NSE sectors and their mapped tickers. "
            "Use this to check if a ticker is in the routing table before calling get_news_for_ticker."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

TOOL_HANDLERS = {
    "get_news_for_ticker": handle_get_news_for_ticker,
    "list_sectors": handle_list_sectors,
}


def send_response(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def send_error(request_id: Any, code: int, message: str) -> None:
    send_response({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    })


def handle_request(req: dict) -> None:
    req_id = req.get("id")
    method = req.get("method", "")

    if method == "initialize":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "rss-news-swinglens",
                    "version": "1.0.0",
                },
            },
        })

    elif method == "initialized":
        pass  # notification, no response

    elif method == "tools/list":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        })

    elif method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        if tool_name not in TOOL_HANDLERS:
            send_error(req_id, -32601, f"Unknown tool: {tool_name}")
            return

        try:
            result_text = TOOL_HANDLERS[tool_name](tool_args)
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result_text}],
                    "isError": False,
                },
            })
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"[ERROR] {exc}"}],
                    "isError": True,
                },
            })

    elif method == "ping":
        send_response({"jsonrpc": "2.0", "id": req_id, "result": {}})

    else:
        # Unknown method — send error for requests, ignore for notifications
        if req_id is not None:
            send_error(req_id, -32601, f"Method not found: {method}")


def main() -> None:
    logger.info("SwingLens RSS MCP server starting on stdio")
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            req = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            send_error(None, -32700, f"Parse error: {exc}")
            continue
        try:
            handle_request(req)
        except Exception as exc:
            logger.exception("Unhandled error in handle_request")
            send_error(req.get("id"), -32603, f"Internal error: {exc}")


if __name__ == "__main__":
    main()
