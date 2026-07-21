---
name: sector-news-router
description: Routes NSE stock tickers to their relevant news RSS feeds by sector. Use this skill whenever you need to fetch, filter, or recommend news sources for a specific NSE ticker or sector — including when building news context for Groq briefs, when filtering macro news for a specific stock, when someone asks "which news feeds are relevant for HDFC Bank / Infosys / Reliance", or when constructing the news input block for brief.py or any LLM prompt that needs sector-relevant Indian market news. Always use this skill before fetching any news feed in the SwingLens project.
---

# Sector News Router

Maps NSE tickers and sectors to their most relevant RSS news feeds for Indian equity swing trading context.

## How to use this skill

1. Identify the ticker's sector (use the sector map below or the `instruments` table in `analyses.db`)
2. Look up the sector in the Feed Directory to get the feed URLs
3. Always include the Universal Indian Market feeds alongside sector-specific feeds
4. Pass the combined feed list to `news-feed-fetcher` skill for actual fetching

---

## Sector → Ticker Quick Map

Common Nifty 50 tickers by sector (not exhaustive — check `instruments` table for full list):

| Sector | Key Tickers |
|--------|------------|
| Banking & Finance | HDFCBANK, ICICIBANK, KOTAKBANK, AXISBANK, SBIN, BAJFINANCE, BAJAJFINSV |
| IT & Technology | INFY, TCS, WIPRO, HCLTECH, TECHM, LTIM |
| Oil & Gas / Energy | RELIANCE, ONGC, BPCL, IOC |
| Pharma & Healthcare | SUNPHARMA, DRREDDY, CIPLA, DIVISLAB, APOLLOHOSP |
| FMCG & Consumer | HINDUNILVR, ITC, NESTLEIND, BRITANNIA, MARICO |
| Auto & Auto Ancillary | MARUTI, TATAMOTORS, M&M, BAJAJ-AUTO, EICHERMOT, HEROMOTOCO |
| Metals & Mining | TATASTEEL, JSWSTEEL, HINDALCO, COALINDIA, VEDL |
| Cement & Infrastructure | ULTRACEMCO, GRASIM, ADANIENT, ADANIPORTS, LT |
| Telecom | BHARTIARTL |
| Power & Utilities | POWERGRID, NTPC, ADANIGREEN |
| Paint & Chemicals | ASIANPAINT, PIDILITIND |

---

## Feed Directory

> **Last verified: 2026-06-29**

All feeds are **Livemint + The Hindu BusinessLine** only. The previous Reuters,
Economic Times, MoneyControl, Business Standard, and RBI feeds were removed —
confirmed dead (DNS/404) or bot-blocked. Only three feed groups remain:
Universal (every ticker), an IT supplement, and a generic supplement for all
other sectors. Pass Universal + the relevant supplement to `news-feed-fetcher`.

### Universal — Always Include (every ticker, every brief)

```
https://www.livemint.com/rss/markets
https://www.livemint.com/rss/companies
https://www.thehindubusinessline.com/markets/?service=rss
```

These cover FII flows, broad market sentiment, and India macro — relevant for every NSE swing trade regardless of sector.

### Banking & Finance — supplement

```
https://www.livemint.com/rss/money
https://www.thehindubusinessline.com/money-and-banking/?service=rss
```

### IT & Technology — supplement

```
https://www.livemint.com/rss/technology
https://www.thehindubusinessline.com/info-tech/?service=rss
```

### All other sectors — supplement (fallback)

```
https://www.livemint.com/rss/industry
https://www.thehindubusinessline.com/companies/?service=rss
```

Livemint and BusinessLine have no finer per-sector RSS granularity, so every
sector other than Banking and IT shares this generic supplement. The per-sector
context below still applies — it tells you *what to read for* in those feeds,
even though the feed URLs are shared.

---

## Per-Sector Context (what to watch — feeds are shared, see above)

| Sector | Why it moves | Key signals | Feeds |
|--------|--------------|-------------|-------|
| Banking & Finance | RBI rate decisions, credit growth, NPA disclosures, FII flows | RBI MPC dates, credit policy, quarterly NPA results, SEBI banking circulars | Universal + banking supplement |
| IT & Technology | USD strength, US tech spending, deal wins/losses, visa policy | USD/INR, US Fed decisions, US PMI, TCS/Infy deal announcements | Universal + IT supplement |
| Oil & Gas / Energy | Crude price (Brent/WTI) drives ONGC/BPCL/IOC margins; Reliance refining | Brent crude, OPEC decisions, Middle East escalation, India fuel price revisions | Universal + fallback |
| Pharma & Healthcare | USFDA alerts, drug approvals, patent cliffs (binary events) | USFDA import alerts, 483 observations, ANDA approvals, US drug pricing | Universal + fallback |
| FMCG & Consumer | Rural demand, input-cost inflation, monsoon sentiment | CPI inflation, monsoon progress, crude (packaging costs), rural wages | Universal + fallback |
| Auto & Auto Ancillary | Monthly sales (binary), fuel prices, EV policy, metal input costs | SIAM/FADA monthly sales (1st of month), steel/aluminium, EV policy, semiconductors | Universal + fallback |
| Metals & Mining | China demand primary; domestic infra spend, coal/iron ore prices | China PMI/steel demand, LME prices, Coal India output, infra budget | Universal + fallback |
| Cement & Infrastructure | Govt capex cycle, real-estate demand, monsoon slowdown | Budget infra allocation, NHAI awards, real-estate launches, monsoon (Jul–Sep slow) | Universal + fallback |
| Telecom | ARPU trends, spectrum auctions, TRAI decisions | TRAI tariff orders, 5G rollout, Jio/Airtel subscriber data, spectrum costs | Universal + fallback |
| Power & Utilities | Renewables policy, seasonal demand peaks, coal supply | Power Ministry announcements, Coal India supply, renewable targets, PLI updates | Universal + fallback |

---

## Usage Notes

**Max feeds per brief:** Feed no more than 5–7 URLs to `news-feed-fetcher` at once — universal (3) + sector supplement (2) = 5. More than this bloats the Groq context window.

**Feed freshness:** RSS feeds for Indian sources update every 15–60 minutes during market hours (9:15 AM – 3:30 PM IST). Running `brief.py` at 6:30 AM means feeds will carry previous evening's news — that's fine for swing trading context.

**Governance reminder:** News context informs your *reading* of a setup. It never generates or modifies a trade signal. If macro context contradicts a technical setup, flag it in the brief as "macro headwind" — do not reject the setup on macro grounds alone.

**Missing sector:** If a ticker's sector isn't listed here, default to Universal feeds only and note the gap. Do not invent feed URLs.

---

## Reference files

- `references/india-macro-calendar.md` — recurring Indian macro events by month (RBI MPC dates, Budget, earnings season, auto sales dates)
