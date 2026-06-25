# NSE Trading Analyst — CLAUDE.md

This file is the primary context document for Claude Code working on this project.
Read it fully before making any changes. It governs everything.

---

## What this project is

A **personal paper-trading research tool** for NSE Indian equity cash market.
Built by Gourav Soni. Six months of structured trading education from
The Money School (Saif sir) informs the methodology.

**This is research support only.**
It informs human judgment — it does not replace it.
It never generates trade signals, predictions, or confidence scores.

---

## Governance rules — HARD CONSTRAINTS

These come from `success-criteria.md` and must never be violated in code:

| Rule | Detail |
|------|--------|
| NSE cash equity only | No F&O until 12+ months cash profitability |
| Swing trading | Overnight to ~4 weeks. No intraday scalping |
| Max risk per trade | 1.5% of account. Flag any breach. Never suggest exceeding it |
| No automated execution | The app must never place or suggest placing real orders |
| Paper trading only | 6-month minimum evaluation before live trading considered |
| Methodology pending | Never invent indicator logic — mark sections [PENDING: methodology.md] |

**If any proposed feature violates these rules, refuse and explain why.**

---

## AI model split

| Model | Role | Notes |
|-------|------|-------|
| Claude Sonnet 4 (`claude-sonnet-4-6`) | Primary analysis | Prompt caching enabled |
| Groq Llama 3.3 70B (`llama-3.3-70b-versatile`) | Fallback if Claude unavailable | Free tier, OpenAI-compatible API |
| Groq Llama 3.1 8B | Future: routine tagging | Not yet implemented |
| Local Ollama | Future: offline fallback | Not yet implemented |

Fallback order: Claude → Groq → raise Exception (never silently fail)

---

## Project structure

```
nse-trading-analyst/
├── CLAUDE.md                          ← you are here
├── app.py                             ← Streamlit UI (Phase 1)
├── analyzer.py                        ← AI analysis logic (Claude + Groq)
├── storage.py                         ← SQLite + Obsidian save
├── skills/
│   ├── nse-setup-analysis/
│   │   └── SKILL.md                   ← Analysis rules (system prompt source)
│   └── app-development/
│       └── SKILL.md                   ← How to build/modify this app
├── data/
│   └── analyses.db                    ← SQLite database (auto-created, gitignore)
├── .env                               ← API keys (never commit)
├── .env.example                       ← Template to commit
├── requirements.txt
└── README.md
```

### File ownership

- `analyzer.py` — owns all AI API calls. No AI calls anywhere else.
- `storage.py` — owns all persistence. No DB/file writes anywhere else.
- `app.py` — owns all UI. Calls analyzer and storage, renders results.
- `skills/nse-setup-analysis/SKILL.md` — source of truth for analysis rules.
  Never hardcode analysis rules elsewhere — always load from this file.

---

Critical path: S/R curation → Phase 5d (pipeline verification) 
              → Task Scheduler registration → Phase 6 planning

## Phase roadmap

> Canonical phase map. Source of truth: `context-handoff.md` §3 — keep these in sync.

| Phase | What | Status |
|-------|------|--------|
| Phase 0 | Vault structure (Obsidian 10-folder layout) | ✅ COMPLETE |
| Phase 1 | `methodology.md` v1.0 finalized | ✅ COMPLETE |
| Phase 2 | `system_features.json` (PRD §6 capability areas) | 🟡 UNBLOCKED, not started — Gourav authors |
| Phase 3 | SQLite OHLCV pipeline (all 500 tickers, 3 tables) | ✅ COMPLETE |
| Phase 4 | Telegram bot | ⏸️ DEFERRED — resume 23rd June after India govt block lifts |
| Phase 5a | `screen.py` — daily scanner | ✅ COMPLETE |
| Phase 5b | `analyze.py` — indicator snapshots | ✅ COMPLETE |
| Phase 5c | `brief.py` — daily research brief via Groq | ✅ COMPLETE (2026-06-19) |
| Phase 5d | End-to-end pipeline verification on real data | 🔴 BLOCKED — needs S/R curation first |
| Phase 6 | Streamlit dashboard / History tab / `app.py` | ❓ Not yet planned — starts after 5d verified |

**Critical path:** S/R curation → Phase 5d verification → Task Scheduler registration → Phase 6 planning.

---

## Running the app

```powershell
# Install
pip install -r requirements.txt --break-system-packages

# Configure
copy .env.example .env   # then fill in API keys

# Run
streamlit run app.py
# Opens at http://localhost:8501
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Primary AI provider |
| `GROQ_API_KEY` | Yes (for fallback) | Free at console.groq.com |
| `OBSIDIAN_API_KEY` | Optional | Local REST API plugin key |
| `OBSIDIAN_HOST` | Optional | Default: localhost |

---

## Skills

Before modifying analysis logic → read `skills/nse-setup-analysis/SKILL.md`
Before modifying app structure → read `skills/app-development/SKILL.md`

---

## What Claude Code should do

- Read both SKILL.md files before touching any code
- Follow the file ownership rules above
- Keep `analyzer.py` model-agnostic (same JSON output regardless of provider)
- Keep `storage.py` dependency-free (stdlib only, no requests)
- Ask before adding new dependencies
- Surface governance violations immediately — don't just comply

## What Claude Code must NOT do

- Add any feature that generates buy/sell signals or price predictions
- Add confidence scores or probability estimates to analysis output
- Hardcode analysis rules — they live in SKILL.md only
- Add F&O, futures, or options support
- Add automated order execution of any kind
- Invent indicator logic — always mark [PENDING: methodology.md]
- Commit `.env` or `data/analyses.db`
