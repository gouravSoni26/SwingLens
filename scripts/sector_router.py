"""
sector_router.py — Maps NSE tickers to relevant RSS feed URLs
Part of: macro-context-injector + news-feed-fetcher skills

Copy this file to: D:\\nse-trading-analyst\\scripts\\sector_router.py

Usage:
    from scripts.sector_router import get_feeds_for_ticker
    feeds = get_feeds_for_ticker("HDFCBANK")
"""

# ---------------------------------------------------------------------------
# Universal feeds — always included for every ticker
# ---------------------------------------------------------------------------

# All URLs below are Livemint + The Hindu BusinessLine only — every one verified
# to return a parseable RSS feed with entries (2026-06-29). The old Reuters / ET /
# Moneycontrol / Business Standard feeds were dead (DNS or 404) and were removed.
UNIVERSAL_FEEDS = [
    "https://www.livemint.com/rss/markets",
    "https://www.livemint.com/rss/companies",
    "https://www.thehindubusinessline.com/markets/?service=rss",
]

# ---------------------------------------------------------------------------
# Sector-specific feeds (Livemint + BusinessLine only)
# ---------------------------------------------------------------------------
# Livemint has no per-sector granularity beyond markets/companies/money/
# technology/industry, so several sectors share the industry feed and lean on
# BusinessLine's section feeds for specificity. fetch_feeds dedups across feeds.

SECTOR_FEEDS = {
    "banking_finance": [
        "https://www.livemint.com/rss/money",
        "https://www.thehindubusinessline.com/money-and-banking/?service=rss",
    ],
    "it_technology": [
        "https://www.livemint.com/rss/technology",
        "https://www.thehindubusinessline.com/info-tech/?service=rss",
    ],
    "oil_gas_energy": [
        "https://www.livemint.com/rss/industry",
        "https://www.thehindubusinessline.com/markets/commodities/?service=rss",
    ],
    "pharma_healthcare": [
        "https://www.livemint.com/rss/industry",
        "https://www.thehindubusinessline.com/companies/?service=rss",
    ],
    "fmcg_consumer": [
        "https://www.livemint.com/rss/industry",
        "https://www.thehindubusinessline.com/companies/?service=rss",
    ],
    "auto": [
        "https://www.livemint.com/rss/industry",
        "https://www.thehindubusinessline.com/companies/?service=rss",
    ],
    "metals_mining": [
        "https://www.livemint.com/rss/industry",
        "https://www.thehindubusinessline.com/markets/commodities/?service=rss",
    ],
    "cement_infrastructure": [
        "https://www.livemint.com/rss/industry",
        "https://www.thehindubusinessline.com/economy/?service=rss",
    ],
    "telecom": [
        "https://www.livemint.com/rss/technology",
        "https://www.thehindubusinessline.com/info-tech/?service=rss",
    ],
    "power_utilities": [
        "https://www.livemint.com/rss/industry",
        "https://www.thehindubusinessline.com/economy/?service=rss",
    ],
}

# ---------------------------------------------------------------------------
# Ticker → Sector map
# ---------------------------------------------------------------------------

TICKER_SECTOR_MAP = {
    # Banking & Finance
    "HDFCBANK.NS": "banking_finance",
    "ICICIBANK.NS": "banking_finance",
    "KOTAKBANK.NS": "banking_finance",
    "AXISBANK.NS": "banking_finance",
    "SBIN.NS": "banking_finance",
    "BAJFINANCE.NS": "banking_finance",
    "BAJAJFINSV.NS": "banking_finance",
    "INDUSINDBK.NS": "banking_finance",
    "BANDHANBNK.NS": "banking_finance",
    # IT & Technology
    "INFY.NS": "it_technology",
    "TCS.NS": "it_technology",
    "WIPRO.NS": "it_technology",
    "HCLTECH.NS": "it_technology",
    "TECHM.NS": "it_technology",
    "LTIM.NS": "it_technology",
    "MPHASIS.NS": "it_technology",
    "PERSISTENT.NS": "it_technology",
    # Oil & Gas / Energy
    "RELIANCE.NS": "oil_gas_energy",
    "ONGC.NS": "oil_gas_energy",
    "BPCL.NS": "oil_gas_energy",
    "IOC.NS": "oil_gas_energy",
    "GAIL.NS": "oil_gas_energy",
    "OIL.NS": "oil_gas_energy",
    # Pharma & Healthcare
    "SUNPHARMA.NS": "pharma_healthcare",
    "DRREDDY.NS": "pharma_healthcare",
    "CIPLA.NS": "pharma_healthcare",
    "DIVISLAB.NS": "pharma_healthcare",
    "APOLLOHOSP.NS": "pharma_healthcare",
    "BIOCON.NS": "pharma_healthcare",
    "AUROPHARMA.NS": "pharma_healthcare",
    # FMCG & Consumer
    "HINDUNILVR.NS": "fmcg_consumer",
    "ITC.NS": "fmcg_consumer",
    "NESTLEIND.NS": "fmcg_consumer",
    "BRITANNIA.NS": "fmcg_consumer",
    "MARICO.NS": "fmcg_consumer",
    "DABUR.NS": "fmcg_consumer",
    "GODREJCP.NS": "fmcg_consumer",
    # Auto & Auto Ancillary
    "MARUTI.NS": "auto",
    "TATAMOTORS.NS": "auto",
    "M&M.NS": "auto",
    "BAJAJ-AUTO.NS": "auto",
    "EICHERMOT.NS": "auto",
    "HEROMOTOCO.NS": "auto",
    "TVSMOTOR.NS": "auto",
    # Metals & Mining
    "TATASTEEL.NS": "metals_mining",
    "JSWSTEEL.NS": "metals_mining",
    "HINDALCO.NS": "metals_mining",
    "COALINDIA.NS": "metals_mining",
    "VEDL.NS": "metals_mining",
    "NMDC.NS": "metals_mining",
    "SAIL.NS": "metals_mining",
    # Cement & Infrastructure
    "ULTRACEMCO.NS": "cement_infrastructure",
    "GRASIM.NS": "cement_infrastructure",
    "ADANIENT.NS": "cement_infrastructure",
    "ADANIPORTS.NS": "cement_infrastructure",
    "LT.NS": "cement_infrastructure",
    "SHREECEM.NS": "cement_infrastructure",
    # Telecom
    "BHARTIARTL.NS": "telecom",
    # Power & Utilities
    "POWERGRID.NS": "power_utilities",
    "NTPC.NS": "power_utilities",
    "ADANIGREEN.NS": "power_utilities",
    "TATAPOWER.NS": "power_utilities",
    # Paint & Chemicals (use FMCG feeds — closest match)
    "ASIANPAINT.NS": "fmcg_consumer",
    "PIDILITIND.NS": "fmcg_consumer",
}


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------


def get_feeds_for_ticker(ticker: str) -> list:
    """
    Return list of RSS feed URLs for a given NSE ticker.

    Args:
        ticker: NSE ticker symbol with or without .NS suffix
                e.g. "HDFCBANK" or "HDFCBANK.NS"

    Returns:
        List of RSS feed URLs — universal feeds + sector-specific feeds.
        Falls back to universal feeds only if ticker not in map.
    """
    # Normalise — ensure .NS suffix
    if not ticker.endswith(".NS"):
        ticker_ns = ticker + ".NS"
    else:
        ticker_ns = ticker

    sector = TICKER_SECTOR_MAP.get(ticker_ns)

    if sector and sector in SECTOR_FEEDS:
        sector_specific = SECTOR_FEEDS[sector]
        # Combine: universal first, then sector-specific, deduplicated
        all_feeds = UNIVERSAL_FEEDS + [f for f in sector_specific if f not in UNIVERSAL_FEEDS]
        return all_feeds
    else:
        # Unknown ticker — return universal only
        print(
            f"[ROUTER] No sector mapping for {ticker_ns} — using universal feeds only",
        )
        return UNIVERSAL_FEEDS


def get_sector_for_ticker(ticker: str) -> str:
    """Return the sector name for a ticker, or 'unknown' if not mapped."""
    if not ticker.endswith(".NS"):
        ticker = ticker + ".NS"
    return TICKER_SECTOR_MAP.get(ticker, "unknown")


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    ticker = sys.argv[1] if len(sys.argv) > 1 else "HDFCBANK"
    feeds = get_feeds_for_ticker(ticker)
    sector = get_sector_for_ticker(ticker)
    print(f"\nTicker: {ticker}")
    print(f"Sector: {sector}")
    print(f"Feeds ({len(feeds)}):")
    for f in feeds:
        print(f"  {f}")
