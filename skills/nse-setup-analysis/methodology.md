---
version: v1.0
status: active
last_updated: 2026-06-17
known_gaps:
  - "Section 15.1 (sideways/range rules): awaiting future Saif sir training module — never fill from external sources"
---

# methodology.md — NSE Trading Analyst
**Source:** Saif Sir's Training Notes (The Money School)
**Status:** Active — fills [PENDING: methodology.md] markers in skills/nse-setup-analysis/SKILL.md
**Scope:** NSE cash equity, swing trading only (overnight to ~4 weeks)

---

## 1. Core Framework Philosophy

- Analysis is top-down: Monthly → Weekly → Daily → H1
- Trade only with the dominant trend — identify it before anything else
- Confirmation always precedes entry — hope phase is observation, not action
- All breaches are judged on **candlestick closing basis** only (wicks do not count)
- Never rush a trade — wait for levels to hold and confirm

---

## 2. Timeframe Roles

| Timeframe | Data Range | Role |
|-----------|-----------|------|
| Monthly   | All available data | Macro trend direction, major S/R zones |
| Weekly    | 8 years | Intermediate trend, key levels and patterns |
| Daily     | 2 years | Setup identification, entry-level confluence |
| H1        | 3 months | Entry timing, fine-tuning stop loss placement |

**Rule:** Higher timeframe trend takes precedence. Do not take a trade against the Monthly or Weekly trend unless all timeframes are in explicit alignment.

---

## 3. Trend Analysis — The LTRP Framework

### 3.1 What is a Trend?
A series of consecutive pivot highs and pivot lows in a direction.

- **Uptrend:** Higher Pivot Highs + Higher Pivot Lows
- **Downtrend:** Lower Pivot Highs + Lower Pivot Lows
- **Sideways:** No consistent directional sequence

### 3.2 LTRP (Latest Trend Reversal Price)
The most recent pivot low in an uptrend (or most recent pivot high in a downtrend). This is the key level — if it holds, the trend continues; if breached on close, the trend is broken.

### 3.3 Uptrend Analysis — Step by Step

1. **Hope Phase:** 2 consecutive higher highs and higher lows observed → trend is possible
2. **Confirmation:** 3rd pivot high and 3rd pivot low formed → uptrend confirmed
3. **LTRP = latest pivot low** → draw horizontal line at this level
4. **Entry opportunity:** Price retraces to LTRP → wait for bulls to hold it
5. **Hold condition:** Candlestick close must remain above LTRP (wicks below are acceptable)
6. **Target:** Previous pivot high
7. **Shift LTRP:** Once a new pivot low forms above the old LTRP → shift the line up

### 3.4 Downtrend Analysis — Mirror of Uptrend

- LTRP = latest pivot high (resistance level)
- Entry opportunity: price retraces up to LTRP → wait for bears to hold it
- Hold condition: candlestick close must remain below LTRP
- Target: previous pivot low
- Shift LTRP down when a new (lower) pivot high forms

### 3.5 Breach Scenarios (Three outcomes when LTRP breaks)

| Scenario | What happens | How to trade |
|----------|-------------|--------------|
| **1 — Bulls reconquer** | Price dips below LTRP, then closes back above it and surpasses previous pivot high | Enter on close above LTRP; SL below latest swing low |
| **2 — Bears dominant** | Trend reverses → start downtrend count from scratch (Hope → Confirmation → Trade) | Do not enter long; begin downtrend analysis |
| **3 — Sideways** | Neither side wins; price chops around LTRP | Do not trade the old LTRP; apply sideways/range rules |

### 3.6 Trailing Stop Loss in a Trend

- Enter after uptrend confirmed (3 pivot highs + 3 pivot lows) → entry at Low 4
- Initial SL: below Low 3 (closing basis)
- Once price crosses previous pivot high (High 3) → trail SL up to Low 4 (breakeven)
- Continue trailing: each new pivot low becomes new SL level
- Exit if price closes below current LTRP

---

## 4. Support & Resistance

### 4.1 Support
A level where buying demand overpowers selling supply, causing price to bounce upward.

- **Detection:** Price bounces up from a level at least twice
- **Confirmation:** Price retests the level and holds (third touch = confirmed)
- **Entry:** After third touch confirms the support is holding
- **Stop Loss:** Below support level with a margin of safety (understand the psychology)
- **Target:** Previous pivot high / prior resistance level
- **Breach rule:** Only a candlestick **close below** support counts as a breach (not a wick)
- **On breach:** Stop loss triggered → exit immediately

### 4.2 Resistance
A level where selling supply overpowers buying demand, causing price to turn down.

- **Detection:** Price turns down from a level at least twice
- **Confirmation:** Third touch confirms resistance
- **Entry:** After third touch confirms resistance is holding
- **Stop Loss:** Above resistance level with a margin of safety
- **Target:** Previous pivot low / prior support level
- **Breach rule:** Only a candlestick **close above** resistance counts as a breach

### 4.3 Important Multi-Timeframe Considerations

- Multiple support/resistance levels can exist on a single timeframe
- Since we chart across 4 timeframes, levels exist across all of them — note confluence
- Support/resistance is a **zone/range/area**, not a single price point
- Do not rush to trade — wait for levels to hold

---

## 5. Breakouts & Breakdowns

### 5.1 Resistance Breakout
- Bears give up, bulls take over
- Entry: on the candlestick that closes above resistance
- Stop Loss: just below the broken resistance level
- Volume confirmation: breakout with high volume = strong signal; low volume = weak/suspect

### 5.2 Support Breakdown
- Bulls give up, bears take over
- Entry: on the candlestick that closes below support
- Stop Loss: just above the broken support level
- Volume confirmation: same rule — high volume breakdown = strong signal

---

## 6. Change in Polarity

- A breached **resistance** that holds on a retest becomes **new support**
- A breached **support** that holds on a retest becomes **new resistance**
- This applies to both horizontal S/R and diagonal trendlines
- Always a zone/range — not a single price point
- Two scenarios after a breakout and pullback:
  - **Scenario 1:** Old resistance regained (bears took back control) → no polarity change
  - **Scenario 2:** Old resistance holds as new support → polarity confirmed → trade the bounce

---

## 7. Trendlines & Channels

### 7.1 Trendlines
- **Supporting trendline (uptrend):** Draw across the pivot lows (floor)
- **Resistance trendline (downtrend):** Draw across the pivot highs (ceiling)
- Minimum **3 touch points** required for confirmation — first 2 points mark the line, 3rd confirms
- Entry arrows come from the 3rd touch onward

### 7.2 Channels
- When supporting trendline and resistance trendline are **parallel** → it's a channel
- **Rising channel:** both lines slope upward
- **Falling channel:** both lines slope downward
- Trade: buy at lower channel boundary (support), sell/short at upper channel boundary (resistance)

### 7.3 Trendline Breach Consequences
- **Resistance trendline breach** (breakout): Often leads to strong upward move
- **Supporting trendline breach** (breakdown): Often leads to fierce decline (can be ~50% drops)
- Change in polarity applies to diagonal S/R as well

---

## 8. Price Patterns

### 8.1 Four Categories

| Category | Description |
|----------|-------------|
| Bullish Reversal (Bottom Reversal) | Prior downtrend → pattern forms → price reverses up |
| Bearish Reversal (Top Reversal) | Prior uptrend → pattern forms → price reverses down |
| Bullish Continuation | Prior uptrend → consolidation pattern → uptrend resumes |
| Bearish Continuation | Prior downtrend → consolidation pattern → downtrend resumes |

### 8.2 The 7-Step Flowchart (Applies to ALL patterns)

1. **Prior trend** — identify the trend before the pattern
2. **Detect and label** the important points of the pattern
3. **Mark the Point of Breakout/Breakdown (POB)** with a line
4. **Compute the Target Range (TR)** — height of the pattern
5. **Calculate the Target from POB (TGT)** — project the TR from POB
6. **Check volume action** alongside the POB on breakout/breakdown
7. **Observe for a pullback** (highly possible but not compulsory) — re-entry on pullback is valid

### 8.3 Pattern States

| State | Meaning |
|-------|---------|
| **Highly Probable** | Pattern formed but no breakout yet — setup ready, levels calculated |
| **Active** | Breakout/breakdown has occurred — trade is live |
| **Inactive** | Price failed to maintain breakout — SL triggered |
| **Invalid** | Price moves back through the pattern's own defining points — discard entirely |

### 8.4 Reversal Patterns (List)
Double Bottom, Double Top, Triple Bottom, Triple Top, Rounded Bottom, Rounded Top, Head & Shoulders, Inverse Head & Shoulders, Falling Wedge (bullish), Rising Wedge (bearish)

### 8.5 Continuation Patterns (List)
Bullish/Bearish Symmetrical Triangle, Bullish/Bearish Ascending Triangle, Bullish/Bearish Descending Triangle, Bullish/Bearish Rectangle, Bullish/Bearish Flag

### 8.6 Target Calculation (All Patterns)
- Measure the **height** of the pattern (from key high to key low within pattern)
- Project that same distance from the POB in the breakout direction
- This is the minimum expected target

---

## 9. Volume Analysis

### 9.1 Price + Volume Interpretation

| Price Action | Volume Action | Interpretation |
|-------------|---------------|----------------|
| Increasing | Increasing | Trend continues — confirmed by participation |
| Decreasing | Increasing | Trend continues downward — confirmed |
| Increasing | Decreasing | Caution — reversal possible, trend not supported |
| Decreasing | Decreasing | Caution — reversal possible, trend not supported |

### 9.2 Volume at Breakouts/Breakdowns

| Volume | Signal Strength |
|--------|----------------|
| High volume breakout/breakdown | Strong signal — momentum has conviction |
| Low volume breakout/breakdown | Weak signal — watch for false break |

---

## 10. Gap Theory

| Gap Type | Where Formed | Gap Fill? | Sentiment | Who Trades |
|----------|-------------|-----------|-----------|------------|
| Common Gap | Inside a trading range | Yes | Bulls vs bears fighting | Scalpers |
| Breakaway Gap | At a breakout/breakdown | No | One-way domination post breakout | Smart Money |
| Measuring/Runaway Gap | ~Halfway of the rally/decline | No | Further domination continues | Smart Money |
| Exhaustion Gap | End of rally/decline | Yes | Reversal incoming | FOMO crowd (Donkey Money) |

**Trading rules:**
- Breakaway Gap: Buy with SL below gap candle low
- Measuring Gap: Buy with SL below gap candle low
- Exhaustion Gap: Buy with SL below gap candle low; once gap fills → short with SL above gap fill high
- Common Gap: Trade gap-filling technique

---

## 11. Fibonacci

### 11.1 Retracement
Key levels: **0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%**
These act as support and resistance zones.

- **Retracing upward moves:** Apply from Pivot Low (100%) → Pivot High (0%) → get downside targets/re-entry zones
- **Retracing downward moves:** Apply from Pivot High (100%) → Pivot Low (0%) → get upside targets/re-entry zones

### 11.2 Extension
Same percentage levels. Used when price is in **unchartered territory** (beyond previous pivot).

- **Extension for upward moves:** Pivot Low (100%) → Pivot High (0%) → then mark Retracement Low as third point → get targets above previous high
- Used to project where a move can go when there is no prior resistance level visible

---

## 12. Indicators

### 12.1 Moving Averages — Three Roles
1. **Trend identification** (short-term or long-term)
2. **Support and resistance** identification
3. **Trade setup** via pairs crossover signals

**Pairs Crossover Rules:**
- Short MA crosses Long MA from below to above → **Buy signal**
- Short MA crosses Long MA from above to below → **Sell signal**
- SL for buy: candle prior to crossover low minus 0.50%
- SL for sell: candle prior to crossover high plus 0.50%
- Long MA must be at least **2x** the short MA period (avoid too-frequent signals)
- Common pairs: 5 & 20, 9 & 18, 13 & 36, 50 & 200
- Pairs are timeframe-specific — a pair that works on Daily may not work on Weekly

### 12.2 RSI (Relative Strength Index)
Measures strength of current move vs prior 14 periods. Oscillates 0–100.

| Methodology | RSI Range | Market Condition |
|-------------|-----------|-----------------|
| Traditional | 30–70 | Sideways |
| Bullish empirical | 40 (or observed floor) to 70 | Bullish trend |
| Bearish empirical | 60 (or observed ceiling) to 30 | Bearish trend |
| Volatile markets | 20–80 | Sideways + volatile |

**Key rule:** In a trending market, RSI does not always reach 30/70 — observe where it actually bottoms/tops, and trade those empirical levels instead.

**RSI Divergence:**
- **Bearish Divergence:** Price makes higher highs, RSI makes lower highs → reversal warning
- **Bullish Divergence:** Price makes lower lows, RSI makes higher lows → reversal warning
- Divergence is a warning signal — wait for price confirmation before acting

### 12.3 MACD (Moving Average Convergence & Divergence)
Trend-following momentum indicator. Components: MACD line (fast EMA – slow EMA), Signal line (9-day EMA of MACD), Histogram (distance between MACD and Signal line).

| Crossover | Location relative to 0 | Signal |
|-----------|------------------------|--------|
| MACD crosses Signal from below to above | Below 0 | Golden Cross (strong buy) |
| MACD crosses Signal from below to above | Above 0 | Normal buy |
| MACD crosses Signal from above to below | Above 0 | Dead Cross (strong sell) |
| MACD crosses Signal from above to below | Below 0 | Normal sell |

### 12.4 Bollinger Bands
Plotted 2 standard deviations from 20-period SMA. Bands expand in volatility, contract in calm markets.

**Three plays:**

| Play | Market Condition | Setup |
|------|-----------------|-------|
| **Play 1** | Wide sideways | Upper band = supply zone (short); Lower band = demand zone (buy) |
| **Play 2** | Strong trend | In uptrend: lower band + mean act as support (buy dips to mean/lower band) |
| **Play 3** | Squeeze (low volatility) | Bands converge → watch for close beyond either band → explosive bandwalk in that direction |

**Squeeze signal:** Bands converging to near-contact = low volatility compression → imminent breakout. Direction confirmed by which band closes beyond first.

---

## 13. Entry, Stop Loss & Target — Summary Rules

| Element | Rule |
|---------|------|
| Entry | Only after confirmation (3rd touch of level, or close beyond POB) |
| Stop Loss | Below support / above resistance with margin of safety — on closing basis |
| Target | Previous pivot high (longs) / previous pivot low (shorts); or pattern target via height projection |
| Trailing SL | Trail to each new LTRP as trend progresses — locks in profit, limits loss |
| Risk per trade | Maximum 1.5% of capital — non-negotiable |
| Breach | Always judged on candlestick close — wicks do not count |

---

## 14. What Disqualifies a Setup

- LTRP breached on closing basis before entry → do not enter
- Uptrend entry against Monthly/Weekly downtrend (no timeframe alignment)
- Volume absent at breakout → suspect signal, do not act
- Pattern goes Invalid (price moves back through pattern's defining points)
- RSI/MACD indicator divergence without price confirmation
- Risk calculation exceeds 1.5% of capital
- F&O instrument (out of scope — NSE cash equity only)
- Intraday scalp (less than overnight hold — out of scope)

---

## 15. Pending & Research Processes

### 15.1 Sideways / Range Trading Rules
**Status: Awaiting future training module**

Slide 26 of the training notes explicitly states: *"follow sideways rules you will learn in program."* Saif sir has specific sideways rules that have not been covered yet in the course. This section must not be filled with generic internet-sourced rules — doing so risks conflict with the actual framework when it is taught.

**Until this module is complete:**
- If all 4 timeframes show sideways/unclear structure → mark setup as `not_applicable` in the analyzer
- Do not attempt to generate a sideways trade signal
- Update this section only from Saif sir's training when available

---

### 15.2 MA Pairs Research Process (Per Instrument)

The training notes state: *"The entire effort of you as a researcher is to find appropriate pairs which make sense and help you time the market accurately."* MA pairs are empirical and instrument-specific — no universal pair works across all stocks. The process below is how to find the right pair for a given stock.

**Step-by-step research process:**

1. **Pull historical data** for the stock on the target timeframe (Daily / Weekly)
2. **Apply candidate pairs** one at a time on historical chart: start with the common pairs taught — `5 & 20`, `9 & 18`, `13 & 36`, `50 & 200`
3. **Check the long MA is at least 2× the short MA** — pairs like `5 & 8` are too close and produce too many false signals
4. **Count signal quality** over at least 2 years of data:
   - How many crossover signals occurred?
   - How many were followed by a meaningful move in the signal direction?
   - How many were false (price reversed quickly)?
5. **Select the pair with the highest signal-to-noise ratio** for that stock on that timeframe
6. **Record findings** in the trade journal per instrument — a pair that works on Daily for Stock A may not work on Weekly for Stock A, and will likely differ for Stock B
7. **Re-evaluate periodically** — market regimes change, pairs can stop working

**Note:** MA pairs are a timing tool, not a primary signal. Always confirm with trend direction (LTRP), support/resistance levels, and volume before acting on a crossover.

---

### 15.3 RSI Empirical Levels Research Process (Per Instrument)

The training notes state: *"Incase security does not go down till 30, see where it goes down till and then trade those triggers."* RSI levels are observational — they must be discovered per instrument, not assumed.

**Step-by-step research process:**

1. **Pull 2 years of daily data** for the stock
2. **Plot RSI(14)** and identify the prevailing market phase (bullish / bearish / sideways)
3. **In a bullish stock:** Note the lowest RSI reading during each pullback before the stock bounced — record these over 8–10 instances. The floor (e.g. 40, 45, 50) is the empirical oversold level for that stock in that phase
4. **In a bearish stock:** Note the highest RSI reading during each bounce before the stock dropped — record these over 8–10 instances. The ceiling (e.g. 55, 60) is the empirical overbought level
5. **Use the observed floor/ceiling** as your RSI trigger level for that stock, not the generic 30/70
6. **Record per instrument in the trade journal** — update if the market phase changes (a stock shifting from bearish to bullish will have different empirical RSI levels)
7. **Never hardcode 30/70 as the only levels** — treat them as the starting reference, not the rule

**Note:** RSI divergence signals (Section 12.2) still apply regardless of empirical level calibration — a divergence at any level is a warning worth noting.

---

*Last updated: June 2026 — from Saif sir's Money School training notes*
*Do not modify indicator logic or add new rules without updating this file first*
*Section 15.1 must only be updated from Saif sir's training — do not fill from external sources*
