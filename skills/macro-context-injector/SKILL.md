---
name: macro-context-injector
description: Structures and injects macro/news context into Groq brief prompts for SwingLens. Use this skill whenever you are modifying brief.py, rebuilding the Groq prompt, adding news context to a ticker brief, or tuning the prompt structure for better AI output quality. Also use when someone asks "how should I add news to the brief" or "how do I structure the Groq prompt" or "the brief is ignoring macro context". This skill is the single source of truth for Groq prompt structure in SwingLens — never restructure brief.py prompts without consulting it.
---

# Macro Context Injector

Defines the canonical Groq prompt structure for SwingLens ticker briefs, including how to inject news context without diluting technical analysis quality.

## Core principle

The brief has two inputs:
1. **Technical snapshot** — RSI, MACD, BB, volume, S/R proximity (already in `brief.py`)
2. **Macro/news context** — fresh headlines from `news-feed-fetcher` (new addition)

The prompt must treat these as **separate, clearly labelled sections**. Groq must never conflate them — macro context informs the narrative, technical snapshot drives the setup assessment.

---

## Canonical Prompt Structure

This is the exact structure to use in `brief.py`. Replace existing prompt with this template:

```python
BRIEF_PROMPT_TEMPLATE = """
You are a swing trading research assistant for NSE Indian equity markets.
Your role is research support only. Never generate trade signals, predictions, or confidence scores.
Methodology: {methodology_summary}

---

## Macro & News Context (last 24h)
{news_context}

---

## Technical Snapshot — {ticker}
Timeframe: Daily (primary) | Weekly + Monthly (bias confirmation)

RSI (Wilder, 14): {rsi_14}
MACD: Line {macd_line} | Signal {macd_signal} | Histogram {macd_hist}
Bollinger Bands (20, 2): Upper {bb_upper} | Mid {bb_mid} | Lower {bb_lower}
Price vs BB Mid: {price_vs_bb}
Volume (today): {vol_daily:,.0f} | 20-day SMA: {vol_sma_20:,.0f} | Ratio: {vol_ratio:.2f}x

Nearest Support: {nearest_support} ({support_distance_pct:.1f}% away)
Nearest Resistance: {nearest_resistance} ({resistance_distance_pct:.1f}% away)
S/R Zone: {sr_zone}

---

## Brief Instructions

Write a concise research brief (150-200 words) covering:

1. **Setup context** — What does the technical picture show? Is price near S/R? RSI state? MACD direction?
2. **Volume reading** — Is volume confirming or diverging from price action?
3. **Macro overlay** — Does the news context support, contradict, or is neutral to the technical setup? Name the specific headline if relevant.
4. **Watch for** — One specific thing to monitor in the next 1-3 sessions.

Rules:
- Never say "buy", "sell", "enter", "exit", "target", or "stop loss"
- Never assign a confidence score or probability
- If news context says "No recent news available", skip the macro overlay section
- If all timeframes are sideways/unclear, state "Setup not applicable — range-bound conditions"
- Flag any FORBIDDEN_WORDS if present in your output before submitting

FORBIDDEN_WORDS: {forbidden_words}
"""
```

---

## How to wire into brief.py

### Step 1 — Import the fetcher

Add at the top of `brief.py`:
```python
from scripts.fetch_feeds import fetch_news_context
from scripts.sector_router import get_feeds_for_ticker
```

### Step 2 — Fetch news before building prompt

Inside your brief generation function, before constructing the prompt:
```python
# Fetch news context
feed_urls = get_feeds_for_ticker(ticker)
news_context = fetch_news_context(
    feed_urls=feed_urls,
    ticker=ticker,
    max_items_per_feed=3,
    max_age_hours=24
)
```

### Step 3 — Build the prompt

```python
prompt = BRIEF_PROMPT_TEMPLATE.format(
    methodology_summary=METHODOLOGY_SUMMARY,  # see below
    news_context=news_context,
    ticker=ticker,
    rsi_14=rsi_14,
    macd_line=macd_line,
    macd_signal=macd_signal,
    macd_hist=macd_hist,
    bb_upper=bb_upper,
    bb_mid=bb_mid,
    bb_lower=bb_lower,
    price_vs_bb=price_vs_bb,
    vol_daily=vol_daily,
    vol_sma_20=vol_sma_20,
    vol_ratio=vol_ratio,
    nearest_support=nearest_support,
    nearest_resistance=nearest_resistance,
    support_distance_pct=support_distance_pct,
    resistance_distance_pct=resistance_distance_pct,
    sr_zone=sr_zone,
    forbidden_words=", ".join(FORBIDDEN_WORDS),
)
```

### Step 4 — Send to Groq (unchanged from current brief.py)

```python
response = groq_client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=400,
    temperature=0.3,  # keep low — research output, not creative
)
brief_text = response.choices[0].message.content.strip()
```

---

## Methodology Summary Constant

Add this constant near the top of `brief.py` (derive from your `methodology.md`):

```python
METHODOLOGY_SUMMARY = (
    "Saif sir's swing trading methodology: "
    "Multi-timeframe S/R (Monthly/Weekly bias, Daily entry), "
    "RSI Wilder smoothing (14), MACD 12/26/9, BB 20/2, "
    "volume confirmation required, LONG_ONLY in current phase, "
    "1H candles for entry timing only."
)
```

Keep this under 50 words — it's a reminder to Groq, not a full methodology dump.

---

## Context Window Budget

Groq llama-3.3-70b context window: 128k tokens. Not a concern for this prompt.
But keep discipline anyway — bloated prompts produce bloated briefs.

| Section | Target size |
|---|---|
| System framing | ~50 words |
| Methodology summary | ~50 words |
| News context | 5–15 lines (~150 words max) |
| Technical snapshot | ~100 words |
| Brief instructions | ~100 words |
| **Total prompt** | **~450 words** |
| **Brief output** | **150–200 words** |

If news context exceeds 15 lines, `fetch_news_context()` is misconfigured — check `TOTAL_HEADLINE_CAP` in `fetch_feeds.py`.

---

## FORBIDDEN_WORDS list

Keep in sync with current `brief.py` governance check:

```python
FORBIDDEN_WORDS = [
    "buy", "sell", "purchase", "long", "short",
    "enter", "exit", "target", "stop loss", "stop-loss",
    "predict", "forecast", "will", "confidence",
    "guaranteed", "certain", "definitely",
]
```

---

## Prompt Tuning Rules

**Do not change:**
- The two-section structure (macro first, technical second)
- The FORBIDDEN_WORDS check
- The "no signals" framing in system instructions
- Temperature (keep at 0.3)

**You can adjust:**
- Brief word count (150–200 is the sweet spot — don't go above 250)
- The "Watch for" section phrasing
- Which technical fields to include (add/remove per methodology updates)

---

## Reference files

- `references/prompt-versions.md` — changelog of prompt structure changes over time
- `scripts/sector_router.py` — companion script to `fetch_feeds.py`, maps ticker → feed URLs
