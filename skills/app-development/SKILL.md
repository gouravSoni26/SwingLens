---
name: nse-app-development
description: >
  Use this skill when building, modifying, or debugging the NSE Trading Analyst
  application. Triggers include: adding features to app.py, modifying analyzer.py
  or storage.py, upgrading from Streamlit to React/FastAPI, adding new AI providers,
  changing the report layout, adding new storage backends, or any structural change
  to this project. Always read this skill before touching any file in the project.
  Do NOT use for generic Python/Streamlit/React questions unrelated to this app.
---

# NSE Trading Analyst — App Development Skill

## Project purpose (never lose sight of this)

Research support tool for paper-traded NSE swing trading.
Every feature must serve this purpose. Every feature must respect governance.
Read `CLAUDE.md` before this file — it is the primary authority.

---

## Architecture pattern

```
User describes chart
        ↓
app.py (UI layer)
        ↓
analyzer.py (AI layer) ← reads SKILL.md as system prompt
        ↓        ↓
   Claude API   Groq API (fallback)
        ↓
  JSON response (same schema from both providers)
        ↓
app.py renders report
        ↓
storage.py (persistence layer)
        ↓
   SQLite      Obsidian REST API
```

**One-way data flow. No shortcuts between layers.**

---

## analyzer.py — the AI layer

### Rules
- Loads `skills/nse-setup-analysis/SKILL.md` as the system prompt
- Never hardcodes analysis rules inline
- Claude gets prompt caching (`cache_control: ephemeral`) — cuts cost ~90%
- Groq gets plain text system prompt (no cache_control — not supported)
- Both providers must return the **same JSON schema**
- Fallback order: Claude → Groq → raise Exception
- Never silently swallow errors — always surface which provider failed

### Adding a new AI provider

1. Add a `_call_{provider}(system_text, user_msg) -> dict` function
2. Add it to the fallback chain in `analyze_setup()`
3. Add its API key to `.env.example` and `CLAUDE.md` env table
4. Test with a known setup to confirm JSON schema matches

### JSON schema (must never change without updating all providers)

```json
{
  "ticker": "string",
  "timeframes": {
    "monthly": {"trend": "string", "levels": ["string"], "view": "bullish|bearish|neutral|unclear|not_described"},
    "weekly":  {"trend": "string", "levels": ["string"], "view": "..."},
    "daily":   {"trend": "string", "levels": ["string"], "view": "..."},
    "h1":      {"trend": "string", "levels": ["string"], "view": "..."}
  },
  "bullish_count": 0,
  "alignment_summary": "string",
  "risk": {"entry": null, "sl": null, "target": null, "risk_pct": null, "rr": null, "risk_pass": null},
  "governance": {
    "nse_cash": "pass|fail|unknown",
    "swing_period": "pass|fail|unknown",
    "not_intraday": "pass|fail|unknown",
    "risk_limit": "pass|fail|not_calculable",
    "no_auto": "pass"
  },
  "governance_overall": "clear|needs_review|blocked",
  "narrative": "2-4 sentence plain summary",
  "missing_info": ["string"]
}
```

---

## storage.py — the persistence layer

### Rules
- stdlib only — no `requests`, no `httpx`. Use `urllib.request` for Obsidian.
- Two backends: SQLite (always) + Obsidian (optional, requires open app)
- `init_db()` must be called once at app startup — idempotent
- Obsidian notes go to `Trading/Analyses/{TICKER}-{DATE}.md`
- Obsidian uses self-signed cert — always `ssl.CERT_NONE` for localhost
- Returns `(bool, str)` tuples — never raises on save failure; let UI handle it

### Adding a new storage backend

1. Add a `save_to_{backend}(analysis: dict, ...) -> tuple[bool, str]` function
2. Never change the SQLite schema without a migration
3. Add config to `.env.example`

---

## app.py — the UI layer

### Phase 1: Streamlit rules
- `st.form()` wraps all inputs — prevents re-runs on each keystroke
- `st.session_state` holds last analysis and loaded history item
- `render_report()` is the single function that renders everything — keep it pure
- HTML is rendered via `st.markdown(html, unsafe_allow_html=True)`
- Colors: use the VIEW_STYLE dict — never hardcode colors inline
- Save buttons appear only after analysis renders — never inside the form

### Adding a new report section

1. Add the field to the JSON schema in `analyzer.py`
2. Update the system prompt in `skills/nse-setup-analysis/SKILL.md`
3. Add a render helper function (e.g. `def new_section_html(data) -> str`)
4. Call it inside `render_report()` in the right position
5. Add the column to the SQLite schema with a migration if it needs to be stored

### Phase 2: React + FastAPI upgrade path

When upgrading, follow this order strictly:
1. Create `api/` folder — do NOT touch `analyzer.py` or `storage.py`
2. Create `api/main.py` (FastAPI app)
3. Create `api/routes/analyze.py` — wraps `analyze_setup()` as POST /analyze
4. Create `api/routes/history.py` — wraps `get_history()` and `get_by_id()`
5. Create `frontend/` (React + Vite)
6. Keep `app.py` working throughout — deprecate it only after React is tested
7. The React frontend should replicate the same visual design already built

---

## Groq integration pattern

```python
import groq as groq_sdk
import os

GROQ_MODEL = "llama-3.3-70b-versatile"

def _call_groq(system_text: str, user_msg: str) -> dict:
    client = groq_sdk.Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_text},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.1,   # low temp = consistent JSON structure
        max_tokens=1000,
    )
    text  = response.choices[0].message.content
    clean = text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)
```

Key differences from Claude:
- OpenAI-compatible API (`choices[0].message.content` not `content[0].text`)
- No prompt caching (cost is already free on Groq)
- `temperature=0.1` for JSON consistency
- Same system prompt text — no `cache_control` wrapper

---

## Checklist before any PR / commit

- [ ] `CLAUDE.md` governance rules still respected
- [ ] No trade signals, predictions, or confidence scores added
- [ ] `analyzer.py` still loads system prompt from `skills/nse-setup-analysis/SKILL.md`
- [ ] Both Claude and Groq paths tested with a sample setup
- [ ] New `.env` variables documented in `.env.example` and `CLAUDE.md`
- [ ] `data/analyses.db` and `.env` in `.gitignore`

---

## File relationships

`skills/nse-setup-analysis/SKILL.md` governs WHAT the analysis says.
This file governs HOW the application is built.
They are complementary — read both when working on analysis features.
