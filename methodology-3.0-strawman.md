## 3.0 Pivot Identification — STRAWMAN DRAFT

> **⚠️ THIS IS A STRAWMAN — NOT YET CANONICAL.**
> Every line is tagged. Correct against Saif sir's training before this replaces/augments §3 in methodology.md.
>
> - `✅ TRANSCRIBED` = taken directly from the slide images. Verify wording only.
> - `⚠️ INFERENCE` = my best guess added so the rule is codeable. **Saif sir's actual rule must overwrite this.** If the training does not specify it, mark the decision explicitly rather than leaving my guess in.
> - `[PENDING: confirm from Saif sir]` = a value/rule the slides do not give. Do not fill from outside sources.

---

### What is a pivot?

`✅ TRANSCRIBED`
- A pivot point is essentially an important (pivotal) swing high or swing low on the chart.
- A pivot is used to determine the overall trend of the market.

### Criteria to mark pivots

`✅ TRANSCRIBED`
- Consider a group of 15–20 candlesticks.
- Pick out the important swing high amongst that particular set of candlesticks.
- Pick out the important swing low amongst that particular set of candlesticks.
- In case of a clash amongst two swings at highs, choose the **higher** one.
- In case of a clash amongst two swings at lows, choose the **lower** one.

### Zig-zag rule (alternation)

`✅ TRANSCRIBED`
- Each pivot high is followed by a pivot low, and each pivot low is followed by a pivot high.
- Mark zig-zag lines across the chart and plot the pivots on them.
- Do not follow a pivot high after a pivot high, or a pivot low after a pivot low. **Remember ZIG-ZAG.**

---

### Mechanics needed to make this computable

> The slides define *what* a pivot is but leave two mechanical questions open. These must be decided to encode the rule. My proposed defaults are marked `⚠️ INFERENCE` — replace with Saif sir's method if it differs.

**M1 — How the 15–20 candle group moves across the chart**

`⚠️ INFERENCE` — Proposed default: **rolling window with alternation enforcement.**
Scan the chart for local swing highs and lows (a candle that is the highest/lowest within roughly a 15–20 candle neighbourhood), then walk left-to-right enforcing the zig-zag rule. This is the reading that best fits the slide's "remember ZIG-ZAG" emphasis.

- Alternative considered (non-overlapping blocks: chop chart into fixed 15–20 candle segments, one high + one low per segment): rejected as default because fixed blocks can split a single important swing across a boundary. **Confirm which Saif sir intends.**

**M2 — Where a "clash" occurs**

`⚠️ INFERENCE` — Proposed default: **clash = two same-type pivots landing adjacent in the zig-zag.**
When the scan produces two pivot highs in a row (no important pivot low between them), they clash → keep the higher, drop the other. Two pivot lows in a row → keep the lower. This is the mechanism that *enforces* alternation, consistent with the zig-zag rule above.

- **Confirm:** is the clash resolved (a) within one 15–20 candle group, or (b) across adjacent groups when alternation breaks? Default assumes (b).

**M3 — What makes a swing "important" (the sensitivity threshold)**

`[PENDING: confirm from Saif sir]`
The slides say "important" but give no numeric test. A computer needs one of the following to separate an important swing from a minor wiggle. **Pick the one Saif sir teaches, or confirm none exists:**

- [ ] Minimum % move from the previous pivot (e.g. swing must move ≥ ___ % to count) — value: `________`
- [ ] Minimum candle distance between consecutive pivots (e.g. ≥ ___ candles apart) — value: `________`
- [ ] N-bar rule (pivot high = highest candle within ___ bars either side) — value: `________`
- [ ] **None — "important" is visual judgment learned with experience.**
  → If this box is checked, detection runs in **propose-and-confirm** mode: the tool proposes pivots at a tunable sensitivity, the trader confirms or adjusts the dial until proposed pivots match their own marking. The calibrated sensitivity is recorded per timeframe.

---

### Per-timeframe application

`✅ TRANSCRIBED` (timeframe roles from §2) + `⚠️ INFERENCE` (LTRP-per-timeframe from this session)
- Pivots are marked independently on each timeframe: **Monthly, Weekly, Daily** (and H1 for entry timing).
- Each timeframe produces its **own** pivot sequence and therefore its **own** LTRP.
- `[PENDING: confirm from Saif sir]` — does the 15–20 candle group size stay constant across all timeframes, or change per timeframe? (Default assumption: same 15–20 group on every timeframe; the candles simply represent different durations.)

---

### Hand-off to LTRP logic (§3.2–§3.6)

Once pivots are marked by the rules above, the existing §3 logic applies unchanged:
- LTRP = latest pivot low (uptrend) / latest pivot high (downtrend) — §3.2
- Hold = candle **close** stays above (uptrend) / below (downtrend) the LTRP; wicks do not count — §1, §3.3
- Shift LTRP when a new pivot low forms above the old (uptrend) — §3.3 step 7
- Breach scenarios 1–3 — §3.5 (scenario 3 / sideways → `not_applicable`, per §15.1)

---

*Strawman generated for correction. Source for all `✅ TRANSCRIBED` lines: Saif sir slide images (pivot definition slide). All `⚠️ INFERENCE` and `[PENDING]` items require Gourav's verification against The Money School training before this section becomes canonical in methodology.md.*
