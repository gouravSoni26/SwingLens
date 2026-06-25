# Phase 3 — SQLite Schema Design
**Project:** NSE AI Trading Analyst
**Date:** 2026-06-17
**Status:** Approved — ready for Claude Code implementation
**Decisions made by:** Gourav (schema interview, this session)

---

## Context

The existing `data/analyses.db` has one table: `analyses` (LLM analysis output, 0 rows).
Phase 3 adds the OHLCV pipeline tables alongside it. No existing tables are modified.

---

## Tables

### 1. `instruments`
Single source of truth for the Nifty 500 universe.
The yfinance fetcher reads from this table — no hardcoded ticker lists in scripts.

```sql
CREATE TABLE instruments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL UNIQUE,   -- e.g. "RELIANCE.NS"
    name        TEXT NOT NULL,          -- e.g. "Reliance Industries Ltd"
    sector      TEXT,                   -- e.g. "Energy" (for scanner filtering later)
    is_active   INTEGER NOT NULL DEFAULT 1,  -- 1=active, 0=removed from Nifty 500
    added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_instruments_ticker ON instruments(ticker);
CREATE INDEX idx_instruments_sector ON instruments(sector);
CREATE INDEX idx_instruments_active ON instruments(is_active);
```

**Notes:**
- `is_active` flips to 0 when a stock is removed from Nifty 500 (rebalances happen twice a year) — no rows deleted, history preserved
- `sector` will be used by the scanner layer in Phase 5 for sector filtering
- Populate once from a Nifty 500 CSV; update at each rebalance

---

### 2. `ohlcv_daily`
Daily candles. Primary decision timeframe per methodology.md.
Lookback: **2 years** on initial fetch.

```sql
CREATE TABLE ohlcv_daily (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT NOT NULL,
    date         DATE NOT NULL,
    open         REAL NOT NULL,
    high         REAL NOT NULL,
    low          REAL NOT NULL,
    close        REAL NOT NULL,       -- adjusted close
    volume       INTEGER NOT NULL,
    fetched_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date),
    FOREIGN KEY (ticker) REFERENCES instruments(ticker)
);

CREATE INDEX idx_ohlcv_daily_ticker_date ON ohlcv_daily(ticker, date);
```

---

### 3. `ohlcv_weekly`
Weekly candles.
Lookback: **8 years** on initial fetch.

```sql
CREATE TABLE ohlcv_weekly (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT NOT NULL,
    date         DATE NOT NULL,       -- week start date (Monday)
    open         REAL NOT NULL,
    high         REAL NOT NULL,
    low          REAL NOT NULL,
    close        REAL NOT NULL,       -- adjusted close
    volume       INTEGER NOT NULL,
    fetched_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date),
    FOREIGN KEY (ticker) REFERENCES instruments(ticker)
);

CREATE INDEX idx_ohlcv_weekly_ticker_date ON ohlcv_weekly(ticker, date);
```

---

### 4. `ohlcv_monthly`
Monthly candles.
Lookback: **all available** (yfinance max, typically 20+ years for large caps).

```sql
CREATE TABLE ohlcv_monthly (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT NOT NULL,
    date         DATE NOT NULL,       -- month start date
    open         REAL NOT NULL,
    high         REAL NOT NULL,
    low          REAL NOT NULL,
    close        REAL NOT NULL,       -- adjusted close
    volume       INTEGER NOT NULL,
    fetched_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date),
    FOREIGN KEY (ticker) REFERENCES instruments(ticker)
);

CREATE INDEX idx_ohlcv_monthly_ticker_date ON ohlcv_monthly(ticker, date);
```

---

### 5. `fetch_log`
Records every fetcher run — both the initial bulk load and daily Task Scheduler runs.
Enables health monitoring without opening a terminal.

```sql
CREATE TABLE fetch_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    run_type        TEXT NOT NULL,      -- 'initial_bulk' | 'daily_update'
    timeframe       TEXT NOT NULL,      -- 'daily' | 'weekly' | 'monthly'
    batch_number    INTEGER,            -- for chunked initial load (Option B)
    tickers_total   INTEGER NOT NULL,
    tickers_success INTEGER NOT NULL,
    tickers_failed  INTEGER NOT NULL DEFAULT 0,
    failed_tickers  TEXT,               -- JSON array of failed tickers
    status          TEXT NOT NULL,      -- 'success' | 'partial' | 'failed'
    error_message   TEXT,
    duration_seconds REAL
);
```

**Notes:**
- `batch_number` tracks progress during the initial bulk load (500 tickers in batches of 50)
- If a batch fails midway, the fetcher checks `fetch_log` to find the last successful batch and resumes from there
- Daily Task Scheduler runs log `run_type = 'daily_update'`

---

### 6. `trades`
Skeleton trades journal. Joins to both `instruments` and `analyses`.
Designed now so Phase 5 backtest/expectancy queries have clean foreign keys from the start.

```sql
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    direction       TEXT NOT NULL DEFAULT 'long',   -- 'long' only (v1 scope)
    status          TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'closed' | 'cancelled'
    entry_date      DATE,
    exit_date       DATE,
    entry_price     REAL,
    exit_price      REAL,
    quantity        INTEGER,
    stop_loss       REAL,
    target          REAL,
    analysis_id     INTEGER,            -- links to analyses.id
    notes           TEXT,               -- Gourav's reasoning / journal entry
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticker) REFERENCES instruments(ticker),
    FOREIGN KEY (analysis_id) REFERENCES analyses(id)
);

CREATE INDEX idx_trades_ticker ON trades(ticker);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_entry_date ON trades(entry_date);
```

---

### 7. `scan_results`
Candidates surfaced by the daily screener (`scripts/screen.py`).
One row per `(scan_date, ticker)` that passed **all three** screening rules.
Research support only — these are candidates for manual review, never signals.

```sql
CREATE TABLE scan_results (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date          DATE NOT NULL,
    ticker             TEXT NOT NULL,
    latest_date        DATE NOT NULL,
    latest_close       REAL NOT NULL,
    breakout_kind      TEXT,            -- 'up' | 'down'
    nearest_level      REAL,            -- S/R level price closest to latest_close
    nearest_level_kind TEXT,            -- 'support' | 'resistance'
    daily_sma50        REAL,
    daily_sma200       REAL,
    weekly_sma20       REAL,
    weekly_sma50       REAL,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scan_date, ticker),
    FOREIGN KEY (ticker) REFERENCES instruments(ticker)
);

CREATE INDEX idx_scan_results_scan_date ON scan_results(scan_date);
CREATE INDEX idx_scan_results_ticker ON scan_results(ticker);
```

**Notes:**
- A re-run for the same `scan_date` overwrites that day's rows (delete-then-insert) — idempotent
- The three rules: S/R proximity (within 2% of a curated zone), breakout (close-basis), SMA trend alignment (daily 50/200 + weekly 20/50, sideways excluded)

---

### 8. `scan_log`
One row per screener run (mirrors `fetch_log` for health monitoring).

```sql
CREATE TABLE scan_log (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at                        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    scan_date                     DATE NOT NULL,
    tickers_total                 INTEGER NOT NULL,
    tickers_scanned               INTEGER NOT NULL,
    candidates                    INTEGER NOT NULL,
    skipped_no_levels             INTEGER NOT NULL DEFAULT 0,
    skipped_insufficient_history  INTEGER NOT NULL DEFAULT 0,
    skipped_stale                 INTEGER NOT NULL DEFAULT 0,
    errors                        INTEGER NOT NULL DEFAULT 0,
    obsidian_status               TEXT,    -- 'saved' | 'failed' | 'skipped'
    obsidian_message              TEXT,
    status                        TEXT NOT NULL,  -- 'success' | 'partial' | 'failed'
    duration_seconds              REAL
);
```

**Notes:**
- `skipped_stale` counts tickers skipped because their feed was too old (daily > 5 calendar days, weekly > 8 calendar days)
- `skipped_no_levels` counts tickers with no active rows in `support_resistance`
- Appended per run (run history preserved); never overwritten

---

### 9. `support_resistance`
Manually-curated S/R levels. The screener reads levels **only** from here — nothing
is auto-detected. A ticker with no active rows is classified `no_levels` and skipped.
S/R is a zone (methodology.md §4.3): `level_high` NULL means a single-price level.
Populate via `scripts/seed_support_resistance.py`.

```sql
CREATE TABLE support_resistance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    timeframe   TEXT NOT NULL DEFAULT 'daily',   -- 'daily' | 'weekly' | 'monthly'
    kind        TEXT NOT NULL,                   -- 'support' | 'resistance'
    level_low   REAL NOT NULL,                   -- zone lower bound (or the price)
    level_high  REAL,                            -- zone upper bound; NULL = single price
    note        TEXT,                            -- why this level (e.g. "3rd touch")
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, timeframe, kind, level_low),
    FOREIGN KEY (ticker) REFERENCES instruments(ticker)
);

CREATE INDEX idx_sr_ticker_active ON support_resistance(ticker, is_active);
```

**Notes:**
- `UNIQUE(ticker, timeframe, kind, level_low)` makes the CSV seeder idempotent (`INSERT OR IGNORE`)
- `is_active` flips to 0 to retire a level without deleting its history

---

### 10. `indicator_snapshots`
Latest hand-rolled indicator values per ticker, written by `scripts/analyze.py`
(Phase 5b). One row per `(ticker, analysis_date)` — a re-run overwrites it (UPSERT).
Covers three timeframes: Daily, Weekly, Monthly. **H1 is intentionally absent** —
there is no `ohlcv_1h` feed yet (see "Deferred" below).
Research support only — raw indicator values for manual review, never signals.

```sql
CREATE TABLE indicator_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL,
    analysis_date       DATE NOT NULL,
    latest_close        REAL,
    latest_date         DATE,
    daily_sma50         REAL,
    daily_sma200        REAL,
    daily_rsi14         REAL,
    daily_macd          REAL,
    daily_macd_signal   REAL,
    daily_macd_hist     REAL,
    daily_bb_upper      REAL,
    daily_bb_mid        REAL,
    daily_bb_lower      REAL,
    weekly_sma20        REAL,
    weekly_sma50        REAL,
    weekly_rsi14        REAL,
    weekly_macd         REAL,
    weekly_macd_signal  REAL,
    weekly_macd_hist    REAL,
    weekly_bb_upper     REAL,
    weekly_bb_mid       REAL,
    weekly_bb_lower     REAL,
    monthly_sma20       REAL,
    monthly_rsi14       REAL,
    monthly_macd        REAL,
    monthly_macd_signal REAL,
    monthly_macd_hist   REAL,
    monthly_bb_upper    REAL,
    monthly_bb_mid      REAL,
    monthly_bb_lower    REAL,
    sma_pair_calibrated INTEGER DEFAULT 0,
    rsi_calibrated      INTEGER DEFAULT 0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, analysis_date)
);

CREATE INDEX idx_indicator_snapshots_ticker ON indicator_snapshots(ticker);
CREATE INDEX idx_indicator_snapshots_date ON indicator_snapshots(analysis_date);
```

**Indicator parameters (provenance):**
- RSI period 14 — methodology.md §12.2; MACD signal 9 — §12.3; Bollinger 20/2sd — §12.4.
- MACD fast/slow 12/26 are industry-standard defaults (§12.3 fixes only the signal at 9).
- Monthly has `monthly_sma20` only (no monthly SMA 50/200) — its BB mid equals the SMA 20.

**Notes:**
- UPSERT on `(ticker, analysis_date)` makes re-runs idempotent (overwrite, never duplicate).
- `sma_pair_calibrated` / `rsi_calibrated` default `0` and are **never set to 1 by `analyze.py`**.
  SMA pairs and RSI thresholds are per-instrument empirical (methodology §15.2 / §15.3);
  calibration is a future **manual** step that flips these flags.
- Created idempotently by `init_indicator_snapshots()` in `scripts/init_db.py`.

---

## Deferred (add later, no schema changes needed)

| Item | When | Notes |
|------|------|-------|
| `ohlcv_1h` table | After Kite Connect wired | Separate table, separate source — won't touch existing tables |
| `raw_close` column | Phase 5 or later | Add to all three OHLCV tables when P&L reconciliation against broker is needed |
| Fundamentals tables | Later phases | Separate pipeline, separate tables |

---

## Entity Relationships

```
instruments (ticker PK)
    │
    ├──── ohlcv_daily (ticker FK)
    ├──── ohlcv_weekly (ticker FK)
    ├──── ohlcv_monthly (ticker FK)
    └──── trades (ticker FK)
                │
                └──── analyses (analysis_id FK)

fetch_log (standalone — no FK, logs fetcher health)
```

---

## What Goes to Claude Code Next

**Prompt for Claude Code Session 1 (Phase 3):**

> "Read `data/analyses.db` to understand the existing schema (one table: `analyses`).
> Then create `scripts/init_db.py` that adds the following new tables to the same DB:
> `instruments`, `ohlcv_daily`, `ohlcv_weekly`, `ohlcv_monthly`, `fetch_log`, `trades`.
> Schema is in `docs/phase3-schema.md`. Use `IF NOT EXISTS` on all CREATE TABLE statements
> so the script is safe to run multiple times. After creating tables, print a summary of
> all tables now in the DB."

**Prompt for Claude Code Session 2 (Phase 3):**

> "Read `scripts/init_db.py` and `docs/phase3-schema.md`.
> Create `scripts/fetch_ohlcv.py` — a yfinance fetcher that:
> 1. Reads active tickers from the `instruments` table
> 2. Fetches Daily (2yr), Weekly (8yr), Monthly (max) OHLCV using yfinance
> 3. Fetches in batches of 50 tickers with resume capability via `fetch_log`
> 4. Uses `INSERT OR REPLACE` to avoid duplicates
> 5. Logs every run to `fetch_log`
> 6. Stores adjusted close only in the `close` column"

---

## Open Questions (carry to Phase 5)

- [ ] `raw_close` column — add to all OHLCV tables when P&L reconciliation needed
- [ ] Exact backtest method for expectancy calculation (underpins Phase 5 scanner)
- [ ] Exit-aid mechanics (how Swing-High / RSI<70 surface against held positions)
- [ ] `system_features.json` (Phase 2) still needs to be authored by Gourav

---

## Change Log

### 2026-06-18 — indicator_snapshots added (Phase 5b)
- Added `indicator_snapshots` (§10), created by `init_indicator_snapshots()` in `scripts/init_db.py`.
- Written by `scripts/analyze.py`: hand-rolled SMA/RSI/MACD/Bollinger over Daily/Weekly/Monthly.
- H1 intentionally omitted (no `ohlcv_1h` feed yet). Calibration flags default 0, never set by `analyze.py`.

### 2026-06-18 — Screener tables added
- Added `scan_results` (§7), `scan_log` (§8), and `support_resistance` (§9) to match the live DB after building `scripts/screen.py` and `scripts/seed_support_resistance.py`.
- `scan_log` includes `skipped_stale` (data-freshness skips); added to existing DBs via an idempotent `ALTER TABLE` migration in `scripts/init_db.py`.
- S/R levels are **manually curated** in `support_resistance` — the screener does not auto-detect levels (decision this session). A ticker with no active levels is skipped (`no_levels`).
