# Prompt Versions Changelog

Track all changes to the Groq brief prompt structure here.
Always add an entry before modifying `BRIEF_PROMPT_TEMPLATE` in `brief.py`.

---

## v2.0 — 2026-06-26

**Change:** Added macro/news context section above technical snapshot.

**Why:** SwingLens briefs were purely technical with no awareness of macro events
(RBI decisions, crude oil moves, sector-specific news). News context now feeds
in from `fetch_feeds.py` via `sector_router.py`.

**Prompt sections added:**
- `## Macro & News Context (last 24h)` — injected from `fetch_news_context()`
- `Macro overlay` bullet in brief instructions
- Fallback handling when no news available

**Template variables added:**
- `{news_context}` — formatted headline string from news-feed-fetcher skill

---

## v1.0 — Initial (brief.py baseline)

**Structure:** Single section — technical snapshot only.

**Sections:**
- System framing (research assistant, no signals)
- Methodology summary
- Technical snapshot (RSI, MACD, BB, Volume, S/R)
- Brief instructions (setup context, volume, watch for)
- FORBIDDEN_WORDS governance check

---

## Prompt Tuning Rules (always respect)

Before making any prompt change, confirm it does not:
1. Ask Groq to generate a trade signal, prediction, or confidence score
2. Remove or weaken the FORBIDDEN_WORDS check
3. Contradict `methodology.md` (Saif sir's framework)
4. Increase brief output above 250 words (context window discipline)
5. Mix macro and technical sections (keep them clearly separated)

Gourav authors all governance substance — Claude refines wording only.
