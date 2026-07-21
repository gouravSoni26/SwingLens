# SwingLens — Multi-Timeframe Indicator Screen — Spec v1

**Status:** Draft for sign-off. No values pending — `SQUEEZE_LOOKBACK` resolved as an instinct-tuned dial (no taught number exists; breakout timing/direction is not predictable, confirmed with Gourav).
**Nature:** New screen inside SwingLens. Not a separate app. Rides the existing DB, pipeline, venv, scheduler, and deployment.
**Governance:** This screen computes and shows facts. It never states direction and never issues a buy/sell/size instruction. *A lens you look through, never a voice you obey.*

---

## 1. Governance rules (fold into methodology.md before code)

1. Every indicator reading shown is a computed fact — a number or a plain yes/no a machine derives exactly.
2. The app never decides trend direction. "Is this stock in an uptrend / downtrend" stays the trader's visual judgment (higher highs / higher lows), same class as pivot marking.
3. The app never sums indicators into a verdict. No "buy," no "bullish," no score, no confidence. The alignment strip reports *that* timeframes agree ("MACD up on all 3") — it never concludes what to do about it.
4. Highlighting ("lit up") points the eye; it does not judge. The trader reads the full row and decides.
5. **Labels flow in, never back out as guidance.** The trader may record a review of any flagged squeeze (real vs noise, and later what happened). The app may show that record back and tally the trader's own accuracy. The app must NEVER feed those labels back as a verdict on a *new* squeeze — no "resembles your winners," no score, no ranking-by-similarity. That would be prediction built on thin, noisy, personal data, and it moves the buy/sell judgment from the human to the tool.

---

## 2. Indicator spec

For each indicator: the fact the app computes, and the rule that lights it up. All computed on **Daily, Weekly, Monthly**.

| Indicator | Fact shown | Lights up when |
|---|---|---|
| MACD | line above / below signal (the signal line is stored as `..._macd_signal`; keep the "trigger" wording in any user-facing brief text per existing governance) | the line crosses the signal — up or down — vs the previous trading day's snapshot |
| RSI (14) | the number | < `RSI_LOW` (30) or > `RSI_HIGH` (70). Regime bands (40/80, 20/60) deferred — see §6 |
| Bollinger — band touch | on upper band / on lower band / middle | price touches or crosses either band (close basis) |
| Bollinger — squeeze | current band width; "tightest in N" | current band width is the smallest in the last `SQUEEZE_LOOKBACK` periods. N is an instinct-tuned dial (default ~20), NOT a taught number — no rule predicts when/which way a squeeze breaks, so the flag reports "volatility is compressed," nothing more |
| Moving-average pairs (5) | which SMA is above which, per pair | the pair crosses (ordering flips) vs the previous snapshot |
| Volume | today ÷ 20-day average (e.g. 2.1x) | ≥ `VOL_NOTABLE` (2.0x); strong flag at ≥ `VOL_STRONG` (5.0x) |
| Candle | green / red | never — context only, no highlight |
| S/R | on support / on resistance / clear | price within `SR_PROXIMITY` of a human-drawn level (from `support_resistance`; the 500-ticker fill is a separate session) |

**Moving-average pairs:** 20&50, 50&100, 50&200, 98&100, 198&200 — each on Daily, Weekly, Monthly.
**Direction is never inferred from any of these.** A Bollinger squeeze lights up as a *fact of low volatility*; whether the eventual break is up or down is read by the trader on the lower timeframe.

---

## 3. Named constants (all tunable, one place)

No magic numbers. All thresholds live in config, not scattered in code.

```
RSI_LOW            = 30
RSI_HIGH           = 70
VOL_NOTABLE        = 2.0        # x of 20-day average
VOL_STRONG         = 5.0
VOL_AVG_WINDOW     = 20         # days
SR_PROXIMITY       = 0.02       # 2% — match existing screener rule; confirm
BB_PERIOD          = 20         # SMA, all timeframes (already in use)
SQUEEZE_LOOKBACK_DAILY   = 20   # instinct dial — tune by feel, not a taught number
SQUEEZE_LOOKBACK_WEEKLY  = 20   # instinct dial
SQUEEZE_LOOKBACK_MONTHLY = 20   # instinct dial
BREACH_BASIS       = "close"   # wicks never count — global methodology rule
```

**Store the number, derive the flag.** The database stores raw readings. "Lit up" is computed in the view layer at render time from these constants. Tuning a threshold is a config edit, never a data migration.

---

## 4. Data / schema changes

**Table:** `indicator_snapshots`. Confirmed wide design — one row per `(ticker, analysis_date)`, timeframes encoded as column prefixes. **No primary-key change. No reader change. `ON CONFLICT(ticker, analysis_date)` upsert unchanged.**

**Migration path:** add columns via the existing `_ensure_column` / `COLUMN_MIGRATIONS` mechanism (already proven — the vol columns were added this way). Every new column paired in `init_db.py` per the source-of-truth rule.

**New columns needed — SMAs for the five pairs** (existing: `daily_sma50`, `daily_sma200`, `weekly_sma20`, `weekly_sma50`, `monthly_sma20`):

- Daily: `daily_sma20`, `daily_sma98`, `daily_sma100`, `daily_sma198`
- Weekly: `weekly_sma98`, `weekly_sma100`, `weekly_sma198`, `weekly_sma200`
- Monthly: `monthly_sma50`, `monthly_sma98`, `monthly_sma100`, `monthly_sma198`, `monthly_sma200`

**Band width (squeeze):** derivable from existing `..._bb_upper` / `..._bb_lower` (no column strictly required). Optionally store `daily_bb_width`, `weekly_bb_width`, `monthly_bb_width` for observability. The "tightest in N periods" evaluation is computed in `analyze.py` against the `ohlcv_{daily,weekly,monthly}` tables directly, because those hold the true per-period series (a weekly squeeze must compare against prior *weeks*, not prior daily snapshots).

**No new columns for cross detection.** MACD crosses and MA-pair crosses are derived by comparing the current snapshot to the previous snapshot for that ticker. (Weekly/monthly cross = the stored weekly/monthly SMA ordering flips between two consecutive daily snapshots.)

**Writer:** `analyze.py` extended to compute the new SMAs (and, if stored, band widths) for all three timeframes in its existing per-ticker pass. It already runs at 06:20 — **no new scheduler job.**

**Deployment:** unchanged — same manual `data/analyses.db` push after the 6 AM run.

**New table — `squeeze_reviews`** (the journaling log; governance rule §1.5 applies):

```
squeeze_reviews:
  id            INTEGER PRIMARY KEY AUTOINCREMENT
  ticker        TEXT NOT NULL
  timeframe     TEXT NOT NULL          -- daily / weekly / monthly
  review_date   DATE NOT NULL          -- when the squeeze was flagged/reviewed
  verdict       TEXT                   -- trader's read: e.g. 'real' / 'noise'
  note          TEXT                   -- free-text journal
  outcome       TEXT                   -- filled in later: what actually happened
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  UNIQUE(ticker, timeframe, review_date)
```

Paired in `init_db.py`. Two sanctioned uses, both read-only-to-the-human:
1. **Tune the dial.** Repeated "noise, not really tight" verdicts → signal to raise `SQUEEZE_LOOKBACK`. Feedback tunes the tool's *sensitivity*, never its opinion.
2. **Score the trader, not the squeeze.** With `outcome` filled in, the app tallies the trader's own hit rate → feeds the probability calibration tracker in `success-criteria.md`. The app keeps score; it never grades a new squeeze.

The app never queries `squeeze_reviews` to influence how a *new* squeeze is displayed. Display of live squeezes depends only on current band width vs `SQUEEZE_LOOKBACK` — never on past labels.

---

## 5. Screen design

Two levels, one screen (fourth page in the multipage app).

**Level 1 — Watchlist (home).**
- One compact row per stock: ticker, price, and only its *lit-up* chips. Each chip tagged with its timeframe (M / W / D), e.g. "W: squeeze", "D: volume 2x".
- Rows with nothing notable read "nothing lit up today" and sink.
- Sort: "most lit up" (busy stocks float to top) / A–Z.
- Facts only — no verdict column.
- Tap a row → opens that stock's diary.
- Rationale: full readings for 500 stocks is unscannable, so the list shows highlights only. Depth lives one tap in.

**Level 2 — Timeframe diary (detail, per stock).**
- Three pages: **Monthly → Weekly → Daily** (top-down, the order a trader reads a chart; the page-turn reinforces the method).
- **Alignment strip** pinned on top: all three timeframes always visible as small factual tags, even while focused on one page — so timeframe agreement (e.g. weekly squeeze + daily uptrend) is never hidden. Reports agreement; never totals it into a call.
- Each page = **Style C** (every reading shown, notable ones highlighted).
- Identical layout on every page (MACD top … candle bottom) so the eye reads each in a glance.
- Page dots (● ● ●) so you always know which page you're on. Arrow / arrow-key / swipe navigation, looping.

**Streamlit reality (v1):** the animated page-flip is a web-animation effect native Streamlit won't reproduce. Ship the same structure with a **segmented control** (Monthly / Weekly / Daily buttons) driving `st.session_state` — same information, same order, instant swap. The true sliding flip is the TradingView-lightweight-charts custom-component road → v2.

---

## 6. Deferred (v2 / later sessions)

- **RSI regime bands** (40/80 uptrend, 20/60 downtrend): needs a trend tag per stock, which is trend judgment. Deferred until Kite/Zerodha history is loaded. The existing `rsi_calibrated` / `sma_pair_calibrated` flag columns are the intended home; default 0 = plain 30/70 + all pairs shown until then. Note: any such tag goes stale (DP-04 lesson) — tag few, re-check periodically, never bulk-tag 500.
- **Fibonacci:** half-and-half (trader picks swing hi/lo by eye, app draws levels). v2.
- **Chart patterns** (H&S, double tops, flags, triangles, cup-and-handle): visual judgment, same family as pivots. v2.
- **Mini candlestick chart per diary page** with S/R lines drawn on it: the natural v2 of the diary.
- **Animated flip / click-to-mark chart:** lightweight-charts custom component. v2.

---

## 7. Open items before build

1. ~~`SQUEEZE_LOOKBACK`~~ — RESOLVED. Instinct dial, default 20 per timeframe, tuned by feel via the `squeeze_reviews` log. No slide-hunt needed.
2. **Confirm pair scope:** all five MA pairs on all three timeframes? (Confirmed in session — restating for the record, since it drives the 13 new columns.)
3. **`SR_PROXIMITY`:** reuse the screener's existing 2% rule, or a different value for this screen?

---

## 8. Build order

1. Fold §1 (governance, incl. rule 5 — labels in, never out) + §2 (rules) + §3 (constants) into `methodology.md` — source of truth before code.
2. Reflect the full spec back as testable rules → sign off.
3. `/plan` in Claude Code.
4. Build: `init_db.py` column additions + `squeeze_reviews` table (paired) → `analyze.py` multi-timeframe extension → derivation layer (crosses, squeeze, lit-flags) → the two-level screen → the squeeze review log.
5. Tests green (currently 71), ruff clean.
