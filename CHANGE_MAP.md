# NSE Trading Analyst — Change Map
**Purpose:** Quick reference for where to make changes in the project
**Last updated:** 11 Jun 2026

---

## 1. UI / Visual Changes → `app.py`

| What you want to change | Where in app.py |
|-------------------------|-----------------|
| Timeframe card colors, text, layout | `tf_card()` function |
| Risk parameters row styling | `risk_row()` function |
| Governance check row styling | `gov_row()` function |
| Full report layout and sections | `render_report()` function |
| Page title, icon, layout | `st.set_page_config()` at top |
| Sidebar content | `with st.sidebar:` block |
| Analyze tab layout | `with tab1:` block |
| History tab layout | `with tab2:` block |
| Clear button behavior | `st.button("🔄 Clear Analysis")` block |
| Provider badge (Claude/Groq) | inside `render_report()` — look for `provider` variable |

---

## 2. Analysis Logic / AI Behavior → `skills/nse-setup-analysis/SKILL.md`

| What you want to change | What to edit |
|-------------------------|-------------|
| Governance rules the AI follows | Section: Hard Governance Rules |
| How the AI analyzes each timeframe | Section: Analysis Process |
| What the AI is not allowed to say | Section: Must Never Output |
| JSON output structure | Section: Output Format |
| Indicator logic (MA, RSI, MACD, BB) | Reference → `methodology.md` Sections 12–13 |
| Setup disqualifiers | Reference → `methodology.md` Section 14 |
| Sideways handling | Section 15.1 — awaiting Saif sir's training |

---

## 3. Methodology Rules → `skills/nse-setup-analysis/methodology.md`

| What you want to change | Which section |
|-------------------------|--------------|
| Trend analysis / LTRP rules | Section 3 |
| Support & Resistance rules | Section 4 |
| Breakout / Breakdown rules | Section 5 |
| Change in Polarity | Section 6 |
| Trendlines & Channels | Section 7 |
| Price Patterns + 7-step flowchart | Section 8 |
| Volume interpretation | Section 9 |
| Gap Theory | Section 10 |
| Fibonacci rules | Section 11 |
| MA Pairs / RSI / MACD / Bollinger | Section 12 |
| Entry, SL, Target rules | Section 13 |
| What disqualifies a setup | Section 14 |
| Sideways rules (pending) | Section 15.1 — do not edit until Saif sir's module |
| MA pairs research process | Section 15.2 |
| RSI empirical levels process | Section 15.3 |

---

## 4. AI API Calls / Model Behavior → `analyzer.py`

| What you want to change | Where in analyzer.py |
|-------------------------|---------------------|
| Switch primary model | `MODEL` constant at top |
| Switch Groq fallback model | `GROQ_MODEL` constant at top |
| Adjust response length | `max_tokens` parameter |
| Change fallback behavior | `analyze_setup()` — try/except block |
| Add a new AI provider | Add new `try` block in `analyze_setup()` |
| Change prompt caching behavior | `cache_control` on system prompt message |
| Change JSON schema | Bottom of `analyze_setup()` + update SKILL.md to match |

---

## 5. Saving Data → `storage.py`

| What you want to change | Where in storage.py |
|-------------------------|---------------------|
| SQLite database location | `DB_PATH` constant at top |
| What fields are saved to SQLite | `save_to_sqlite()` function |
| Obsidian note format / template | `_build_note()` function |
| Obsidian folder path | `vault_folder` parameter in `save_to_obsidian()` |
| Obsidian port (default 27124) | `url` line inside `save_to_obsidian()` |
| History query (what gets shown) | `get_history()` function |

---

## 6. Environment / API Keys → `.env`

| Key | Purpose |
|-----|---------|
| `ANTHROPIC_API_KEY` | Claude primary — not added yet |
| `GROQ_API_KEY` | Groq fallback — active |
| `OBSIDIAN_API_KEY` | Obsidian Local REST API |
| `OBSIDIAN_HOST` | Should be `127.0.0.1` |

---

## 7. Pending Items (Needs Action)

| Item | Where to change | Blocked by |
|------|----------------|-----------|
| Add Anthropic API key | `.env` | Nothing — do anytime |
| Test SQLite save | Run app → analyze → click Save to DB | App running ✅ |
| Test Obsidian save | Run app → open Obsidian → analyze → Save to Obsidian | Obsidian must be open |
| Test History tab | After saving at least one analysis | SQLite save working |
| Sideways rules | `methodology.md` Section 15.1 | Saif sir's future training module |
| MA pairs per stock | `methodology.md` Section 15.2 | Empirical — discover per stock |
| Phase 2 React upgrade | New files: `api/`, React frontend | After Streamlit fully tested |

---

## 8. What Never to Touch Without Reading First

| File | Why |
|------|-----|
| `skills/nse-setup-analysis/SKILL.md` | System prompt for AI — changes affect every analysis |
| `methodology.md` Section 15.1 | Awaiting Saif sir's training — do not fill from external sources |
| `CLAUDE.md` | Claude Code's primary context — changes affect all Claude Code sessions |
| `.env` | Never commit this file to Git |
