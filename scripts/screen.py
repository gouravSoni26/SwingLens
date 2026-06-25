"""Daily batch screener for the NSE Trading Analyst pipeline.

Screens the active Nifty 500 universe against THREE rules that must ALL pass
for a ticker to surface as a candidate:

    Rule 1 — S/R proximity     : latest close is within SR_PROXIMITY_PCT of an S/R level
    Rule 2 — Breakout          : latest daily CLOSE crossed a level (wicks never count)
    Rule 3 — SMA trend align   : bullish SMA alignment on daily AND weekly, not sideways

S/R levels are NOT auto-detected. They are read from the manually-curated
``support_resistance`` table (you populate it from your own chart analysis, e.g.
via scripts/seed_support_resistance.py). A ticker with no active levels is
classified ``no_levels`` and skipped — only curated names can become candidates.

Results are persisted SQLite-first (scan_results + scan_log) and then, as a
best-effort secondary sink, written to Obsidian. If Obsidian is down the run
still succeeds — the SQLite rows are the durable artifact.

RESEARCH SUPPORT ONLY. Output is a list of candidates for manual review. This
script never emits buy/sell signals, predictions, confidence scores, or order
suggestions (see CLAUDE.md governance constraints).

Threshold provenance
--------------------
- Breakout on closing basis (wicks excluded) is methodology.md §1, §4.1-4.2, §5.
- S/R levels are human-curated zones (methodology.md §4.3 "S/R is a zone").
- SMAs are used for TREND IDENTIFICATION (methodology.md §12.1 MA Role 1), NOT
  as the per-instrument crossover pairs-signal of §15.2 / SKILL.md Step 5.
- SR_PROXIMITY_PCT (2%) and SIDEWAYS_SMA_GAP_PCT (1%) are OPERATIONAL screening
  parameters (Gourav's decisions, this session). The sideways check here only
  EXCLUDES flat names from candidates — consistent with §15.1 "mark
  not_applicable" — it is NOT a sideways trading rule.

Schema source of truth: docs/phase3-schema.md + scripts/init_db.py
Usage:
    python scripts/screen.py
    python scripts/screen.py --limit 50        # screen first 50 tickers (testing)
    python scripts/screen.py --no-obsidian      # skip the Obsidian write entirely

pandas is used for SMA calculation (already installed via yfinance). Everything
else is stdlib. storage.py stays stdlib-only and is not imported here.
"""

import argparse
import os
import sqlite3
import ssl
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Load .env so OBSIDIAN_API_KEY (and OBSIDIAN_HOST) are available when this
# script runs standalone, e.g. from Task Scheduler. Mirrors app.py's behaviour.
load_dotenv()

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "analyses.db"

# ── Screening parameters ─────────────────────────────────────────────────────
# methodology-grounded:
DAILY_SMA_SHORT = 50  # §12.1 common pair 50&200
DAILY_SMA_LONG = 200
WEEKLY_SMA_SHORT = 20  # long >= 2x short (§12.1 rule); Gourav's weekly pair
WEEKLY_SMA_LONG = 50

# operational (Gourav's screening decisions — NOT literal methodology numbers):
SR_PROXIMITY_PCT = 2.0  # within 2% of the nearest S/R zone bound (close-basis)
SIDEWAYS_SMA_GAP_PCT = 1.0  # SMAs within 1% of each other => too flat => Rule 3 fails

# Data-freshness gates. The screener must not run rules on a ticker whose feed
# has gone stale (a failed/partial fetch would otherwise surface a phantom
# breakout off an old bar). 5 calendar days ~= 3 trading days (covers a weekend).
DAILY_STALE_DAYS = 5  # daily feed older than this (calendar days) => stale
WEEKLY_STALE_DAYS = 8  # weekly feed older than this (calendar days) => stale

# LONG_ONLY scope: current phase trades long only (trades.direction defaults to
# 'long'). With this True, Rule 2 only counts UP-breakouts (close above
# resistance); down-breakouts are excluded from candidates. Flip to False in a
# future short-selling phase to re-enable down-breakout detection — no other
# code change needed.
LONG_ONLY = True

# Derived minimum history needed before any rule can be evaluated.
MIN_DAILY_BARS = DAILY_SMA_LONG  # need >= 200 daily closes for SMA200
MIN_WEEKLY_BARS = WEEKLY_SMA_LONG  # need >= 50 weekly closes for weekly SMA50

OBSIDIAN_VAULT_FOLDER = "08-Daily-Logs"

# The "no-levels" bucket is the whole un-curated universe (can be hundreds of
# names), so its Needs-Attention row is truncated to keep the note readable.
NO_LEVELS_TICKER_DISPLAY_LIMIT = 10

REQUIRED_TABLES = {"scan_results", "scan_log", "support_resistance"}


# ── Domain types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Level:
    """A curated support/resistance zone. high is None for a single-price level."""

    kind: str  # 'support' | 'resistance'
    low: float
    high: float | None = None

    @property
    def upper(self) -> float:
        """Upper bound of the zone (== low for a single-price level)."""
        return self.high if self.high is not None else self.low


@dataclass(frozen=True, slots=True)
class ScreenResult:
    """Outcome of screening one ticker. status drives the run tally."""

    ticker: str
    status: (
        str  # 'candidate' | 'rejected' | 'no_levels' | 'insufficient_history' | 'stale' | 'error'
    )
    latest_date: str | None = None
    latest_close: float | None = None
    breakout_kind: str | None = None  # 'up' | 'down' | None
    nearest_level: float | None = None
    nearest_level_kind: str | None = None  # 'support' | 'resistance' | None
    daily_sma50: float | None = None
    daily_sma200: float | None = None
    weekly_sma20: float | None = None
    weekly_sma50: float | None = None
    detail: str | None = None  # human-readable note (e.g. error message)
    # Rule-level pass/fail, populated for status="rejected" rows only (None
    # otherwise): lets the Obsidian note explain WHY a curated name was dropped.
    r1_passed: bool | None = None
    r2_passed: bool | None = None
    r3_passed: bool | None = None


# ── Data access (read-only) ──────────────────────────────────────────────────


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-only so the screener can never contend with the fetcher."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_active_tickers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT ticker FROM instruments WHERE is_active = 1 ORDER BY ticker"
    ).fetchall()
    return [r["ticker"] for r in rows]


def load_closes(conn: sqlite3.Connection, table: str, ticker: str) -> pd.DataFrame:
    """Return a date-ordered DataFrame of closes for one ticker.

    Columns: date (str 'YYYY-MM-DD'), close (float). Empty frame if no rows.
    """
    rows = conn.execute(
        f"SELECT date, close FROM {table} WHERE ticker = ? ORDER BY date ASC",
        (ticker,),
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    return pd.DataFrame(rows, columns=["date", "close"])


def load_sr_levels(conn: sqlite3.Connection, ticker: str) -> list[Level]:
    """Read the curated, active S/R levels for a ticker (all timeframes)."""
    rows = conn.execute(
        """
        SELECT kind, level_low, level_high
        FROM support_resistance
        WHERE ticker = ? AND is_active = 1
        """,
        (ticker,),
    ).fetchall()
    return [
        Level(
            kind=r["kind"],
            low=float(r["level_low"]),
            high=None if r["level_high"] is None else float(r["level_high"]),
        )
        for r in rows
    ]


# ── Freshness ────────────────────────────────────────────────────────────────


def is_stale(date_str: str, max_age_days: int, today: date | None = None) -> bool:
    """True if date_str is more than max_age_days calendar days before today."""
    ref = today or date.today()
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (ref - d).days > max_age_days


# ── Level geometry ───────────────────────────────────────────────────────────


def level_distance_pct(close: float, level: Level) -> float:
    """Percent distance from close to the nearest zone bound; 0.0 if inside the zone."""
    if level.low <= close <= level.upper:
        return 0.0
    bound = level.low if close < level.low else level.upper
    if bound == 0:  # zero guard — never divide by a 0 level
        return float("inf")
    return abs(close - bound) / bound * 100.0


def nearest_level(close: float, levels: list[Level]) -> tuple[float | None, str | None]:
    """Return (representative bound price, kind) of the level closest to close."""
    if not levels:
        return None, None
    best = min(levels, key=lambda lv: level_distance_pct(close, lv))
    bound = best.low if abs(close - best.low) <= abs(close - best.upper) else best.upper
    return bound, best.kind


# ── The three rules ──────────────────────────────────────────────────────────


def rule_sr_proximity(close: float, levels: list[Level]) -> bool:
    """Rule 1: latest close within SR_PROXIMITY_PCT of any S/R zone (close-basis)."""
    if not levels:
        return False
    return min(level_distance_pct(close, lv) for lv in levels) <= SR_PROXIMITY_PCT


def rule_breakout(
    closes: pd.Series, levels: list[Level], long_only: bool = LONG_ONLY
) -> str | None:
    """Rule 2: did the latest CLOSE cross a level? Returns 'up' | 'down' | None.

    Up-breakout: previous close <= resistance.upper < latest close (closed above
    the zone). Down-breakout: previous close >= support.low > latest close (closed
    below the zone). Only closes are compared, so wicks never count
    (methodology.md §1, §5).

    When long_only is True (current phase scope), down-breakouts are not counted
    — only up-breakouts can make a ticker a candidate.
    """
    if len(closes) < 2:
        return None
    prev_close = float(closes.iloc[-2])
    curr_close = float(closes.iloc[-1])

    if any(lv.kind == "resistance" and prev_close <= lv.upper < curr_close for lv in levels):
        return "up"
    if not long_only and any(
        lv.kind == "support" and prev_close >= lv.low > curr_close for lv in levels
    ):
        return "down"
    return None


def rule_sma_trend(daily_closes: pd.Series, weekly_closes: pd.Series) -> tuple[bool, dict]:
    """Rule 3: bullish SMA alignment on daily AND weekly, neither sideways.

    Bullish alignment = short SMA above long SMA (methodology.md §12.1 Role 1:
    trend identification). Sideways exclusion = SMAs within SIDEWAYS_SMA_GAP_PCT
    of each other on either timeframe (operational filter; drops flat names so the
    screener never surfaces sideways structure — consistent with §15.1).

    Returns (passed, smas) where smas holds the four latest SMA values.
    """
    d_short = daily_closes.rolling(DAILY_SMA_SHORT).mean().iloc[-1]
    d_long = daily_closes.rolling(DAILY_SMA_LONG).mean().iloc[-1]
    w_short = weekly_closes.rolling(WEEKLY_SMA_SHORT).mean().iloc[-1]
    w_long = weekly_closes.rolling(WEEKLY_SMA_LONG).mean().iloc[-1]

    smas = {
        "daily_sma50": _f(d_short),
        "daily_sma200": _f(d_long),
        "weekly_sma20": _f(w_short),
        "weekly_sma50": _f(w_long),
    }

    # Guard: any NaN means insufficient data for a real comparison.
    if any(pd.isna(v) for v in (d_short, d_long, w_short, w_long)):
        return False, smas

    daily_sideways = abs(d_short - d_long) / d_long * 100.0 < SIDEWAYS_SMA_GAP_PCT
    weekly_sideways = abs(w_short - w_long) / w_long * 100.0 < SIDEWAYS_SMA_GAP_PCT
    if daily_sideways or weekly_sideways:
        return False, smas

    bullish = d_short > d_long and w_short > w_long
    return bool(bullish), smas


def _f(value) -> float | None:
    """Coerce a pandas scalar to float, or None if NaN/missing."""
    return None if value is None or pd.isna(value) else float(value)


# ── Screening one ticker ─────────────────────────────────────────────────────


def screen_ticker(conn: sqlite3.Connection, ticker: str) -> ScreenResult:
    """Apply all three rules to one ticker and classify the outcome."""
    daily = load_closes(conn, "ohlcv_daily", ticker)
    weekly = load_closes(conn, "ohlcv_weekly", ticker)

    if len(daily) < MIN_DAILY_BARS or len(weekly) < MIN_WEEKLY_BARS:
        return ScreenResult(ticker=ticker, status="insufficient_history")

    daily_closes = daily["close"].astype(float)
    weekly_closes = weekly["close"].astype(float)
    latest_close = float(daily_closes.iloc[-1])
    latest_date = str(daily["date"].iloc[-1])
    weekly_date = str(weekly["date"].iloc[-1])

    # Freshness gate — never run rules on a stale feed.
    if is_stale(latest_date, DAILY_STALE_DAYS) or is_stale(weekly_date, WEEKLY_STALE_DAYS):
        return ScreenResult(
            ticker=ticker, status="stale", latest_date=latest_date, latest_close=latest_close
        )

    # Levels are curated, not auto-detected. No levels => skip (pure manual).
    levels = load_sr_levels(conn, ticker)
    if not levels:
        return ScreenResult(
            ticker=ticker, status="no_levels", latest_date=latest_date, latest_close=latest_close
        )

    # Evaluate the three rules independently, then AND them.
    r1 = rule_sr_proximity(latest_close, levels)
    breakout = rule_breakout(daily_closes, levels)
    r2 = breakout is not None
    r3, smas = rule_sma_trend(daily_closes, weekly_closes)

    level_price, level_kind = nearest_level(latest_close, levels)

    status = "candidate" if (r1 and r2 and r3) else "rejected"
    # Rule-level detail is only meaningful for rejected names (a candidate
    # passed all three); leave the flags None for candidates and skips.
    rule_flags = (
        {"r1_passed": r1, "r2_passed": r2, "r3_passed": r3} if status == "rejected" else {}
    )
    return ScreenResult(
        ticker=ticker,
        status=status,
        latest_date=latest_date,
        latest_close=latest_close,
        breakout_kind=breakout,
        nearest_level=level_price,
        nearest_level_kind=level_kind,
        **smas,
        **rule_flags,
    )


# ── Persistence (SQLite first) ───────────────────────────────────────────────


def require_tables(conn: sqlite3.Connection, names: set[str]) -> None:
    """Fail fast with a clear message if any required table is missing."""
    existing = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    missing = names - existing
    if missing:
        raise RuntimeError(f"Missing tables {sorted(missing)}. Run scripts/init_db.py first.")


def save_candidates(
    conn: sqlite3.Connection, scan_date: str, candidates: list[ScreenResult]
) -> None:
    """Overwrite today's candidates (idempotent re-run) then insert the new set."""
    conn.execute("DELETE FROM scan_results WHERE scan_date = ?", (scan_date,))
    conn.executemany(
        """
        INSERT INTO scan_results
            (scan_date, ticker, latest_date, latest_close, breakout_kind,
             nearest_level, nearest_level_kind,
             daily_sma50, daily_sma200, weekly_sma20, weekly_sma50)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                scan_date,
                c.ticker,
                c.latest_date,
                c.latest_close,
                c.breakout_kind,
                c.nearest_level,
                c.nearest_level_kind,
                c.daily_sma50,
                c.daily_sma200,
                c.weekly_sma20,
                c.weekly_sma50,
            )
            for c in candidates
        ],
    )
    conn.commit()


def log_run(
    conn: sqlite3.Connection,
    *,
    scan_date: str,
    total: int,
    scanned: int,
    candidates: int,
    no_levels: int,
    insufficient: int,
    stale: int,
    errors: int,
    obsidian_status: str,
    obsidian_message: str | None,
    status: str,
    duration: float,
) -> None:
    conn.execute(
        """
        INSERT INTO scan_log
            (scan_date, tickers_total, tickers_scanned, candidates,
             skipped_no_levels, skipped_insufficient_history, skipped_stale,
             errors, obsidian_status, obsidian_message, status, duration_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan_date,
            total,
            scanned,
            candidates,
            no_levels,
            insufficient,
            stale,
            errors,
            obsidian_status,
            obsidian_message,
            status,
            round(duration, 2),
        ),
    )
    conn.commit()


# ── Obsidian (best-effort secondary sink) ────────────────────────────────────


def build_scan_note(
    scan_date: str,
    candidates: list[ScreenResult],
    rejected: list[ScreenResult],
    tally: dict,
) -> str:
    """Render the candidate list as a markdown note. Research support only.

    Adds two diagnostic sections so the operator knows what to curate/investigate:
    a "Needs Attention" table (names skipped before rules could run, from the
    ticker lists in ``tally``) and a "Rule-by-Rule Breakdown" of ``rejected``
    names (had levels + history + fresh data but failed one or more rules).
    """
    lines = [
        "---",
        f"date: {scan_date}",
        "type: daily-scan",
        "tags:",
        "  - trading",
        "  - daily-scan",
        "---",
        "",
        f"# Daily Scan — {scan_date}",
        "",
        "> Research support only. Candidates for manual review — **not trade signals**.",
        "",
        f"Scanned {tally['scanned']} of {tally['total']} active tickers · "
        f"{len(candidates)} candidate(s) · "
        f"{tally['insufficient']} insufficient-history · "
        f"{tally['stale']} stale · "
        f"{tally['no_levels']} no-levels · {tally['errors']} error(s).",
        "",
    ]
    if candidates:
        lines += [
            "| Ticker | Close | Breakout | Nearest level | Daily 50/200 | Weekly 20/50 |",
            "|--------|-------|----------|---------------|--------------|--------------|",
        ]
        for c in candidates:
            lines.append(
                f"| {c.ticker} | {c.latest_close:.2f} | {c.breakout_kind or '—'} | "
                f"{(f'{c.nearest_level:.2f} ({c.nearest_level_kind})') if c.nearest_level else '—'} | "
                f"{_fmt(c.daily_sma50)}/{_fmt(c.daily_sma200)} | "
                f"{_fmt(c.weekly_sma20)}/{_fmt(c.weekly_sma50)} |"
            )
    else:
        lines.append("No tickers passed all three rules today.")

    lines += _needs_attention_section(tally)
    lines += _rule_breakdown_section(rejected)

    lines += [
        "",
        "## Rules applied (all must pass)",
        "1. **S/R proximity** — close within "
        f"{SR_PROXIMITY_PCT:g}% of a curated support/resistance zone.",
        "2. **Breakout** — latest close crossed a level (closing basis; wicks excluded).",
        "3. **SMA trend alignment** — bullish on daily (50/200) and weekly (20/50); "
        f"flat structure (SMAs within {SIDEWAYS_SMA_GAP_PCT:g}%) excluded.",
        "",
        "> Levels are human-curated (support_resistance table). "
        "Sideways trade rules remain [PENDING: methodology.md §15.1].",
        "",
        "---",
        "*Generated by NSE Trading Analyst · scripts/screen.py · Paper trading only*",
    ]
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "—"


def _fmt_ticker_list(tickers: list[str], limit: int | None = None) -> str:
    """Comma-join tickers; if limit is given and exceeded, show first `limit`
    then "... and N more". limit=None renders the full list."""
    if limit is not None and len(tickers) > limit:
        remaining = len(tickers) - limit
        return ", ".join(tickers[:limit]) + f", ... and {remaining} more"
    return ", ".join(tickers)


def _needs_attention_section(tally: dict) -> list[str]:
    """Render the "Needs Attention" table for names skipped before rules ran.

    One row per non-empty bucket; the whole section is omitted on a clean run.
    """
    rows: list[tuple[str, list[str], int | None]] = [
        (
            f"Insufficient history (< {MIN_DAILY_BARS} daily candles)",
            tally["insufficient_tickers"],
            None,
        ),
        ("No S/R levels curated", tally["no_levels_tickers"], NO_LEVELS_TICKER_DISPLAY_LIMIT),
        ("Stale data feed", tally["stale_tickers"], None),
    ]
    visible = [(issue, names, limit) for issue, names, limit in rows if names]
    if not visible:
        return []

    lines = [
        "",
        "## ⚠️ Needs Attention",
        "",
        "| Issue | Count | Tickers |",
        "|-------|-------|---------|",
    ]
    for issue, names, limit in visible:
        lines.append(f"| {issue} | {len(names)} | {_fmt_ticker_list(names, limit)} |")
    return lines


def _dropped_at(result: ScreenResult) -> str:
    """First rule a rejected ticker failed (R1, R2, or R3)."""
    if result.r1_passed is False:
        return "R1"
    if result.r2_passed is False:
        return "R2"
    if result.r3_passed is False:
        return "R3"
    return "—"


def _rule_flag(passed: bool | None) -> str:
    """Render a rule pass/fail cell ('—' when the rule was not evaluated)."""
    if passed is None:
        return "—"
    return "pass" if passed else "fail"


def _rule_breakdown_section(rejected: list[ScreenResult]) -> list[str]:
    """Render the per-rule breakdown of rejected (not skipped) tickers.

    Omitted entirely when there are no rejected names.
    """
    if not rejected:
        return []
    lines = [
        "",
        "## Rule-by-Rule Breakdown",
        "",
        "| Ticker | Close | Rule 1 (S/R) | Rule 2 (Breakout) | Rule 3 (SMA) | Dropped at |",
        "|--------|-------|-------------|-------------------|-------------|------------|",
    ]
    for r in rejected:
        close = f"{r.latest_close:.2f}" if r.latest_close is not None else "—"
        lines.append(
            f"| {r.ticker} | {close} | {_rule_flag(r.r1_passed)} | "
            f"{_rule_flag(r.r2_passed)} | {_rule_flag(r.r3_passed)} | {_dropped_at(r)} |"
        )
    return lines


def save_to_obsidian(
    note: str, scan_date: str, api_key: str, host: str = "localhost"
) -> tuple[bool, str]:
    """PUT the scan note into the Obsidian vault via the Local REST API.

    Mirrors the stdlib urllib + self-signed-cert transport used by storage.py.
    Returns (success, message); never raises — the caller treats Obsidian as a
    best-effort secondary sink after SQLite has already been written.
    """
    path = f"{OBSIDIAN_VAULT_FOLDER}/{scan_date}-daily-scan.md"
    url = f"https://{host}:27124/vault/{path}"
    try:
        req = urllib.request.Request(
            url,
            data=note.encode("utf-8"),
            method="PUT",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "text/markdown; charset=utf-8",
            },
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            if resp.status in (200, 201, 204):
                return True, f"Saved to {path}"
            return False, f"Unexpected status {resp.status}"
    except Exception as exc:  # noqa: BLE001 — best-effort; report, never abort
        return False, str(exc)


# ── Orchestration ────────────────────────────────────────────────────────────


def run_screen(limit: int | None, use_obsidian: bool) -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}. Run scripts/init_db.py first.")

    scan_date = datetime.now().strftime("%Y-%m-%d")
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    start = time.monotonic()

    read_conn = open_readonly(DB_PATH)
    try:
        require_tables(read_conn, REQUIRED_TABLES)
        tickers = get_active_tickers(read_conn)
        if limit is not None:
            tickers = tickers[:limit]
        if not tickers:
            print("No active tickers. Run scripts/seed_nifty500.py first.")
            return

        print(f"Scan started {started}")
        print(f"Scan date: {scan_date} | tickers: {len(tickers)}")

        candidates: list[ScreenResult] = []
        rejected: list[ScreenResult] = []
        no_levels_tickers: list[str] = []
        insufficient_tickers: list[str] = []
        stale_tickers: list[str] = []
        errors_count = 0

        for i, ticker in enumerate(tickers, start=1):
            try:
                result = screen_ticker(read_conn, ticker)
            except Exception as exc:  # noqa: BLE001 — isolate one bad ticker
                errors_count += 1
                print(f"  {ticker:<16} ERROR: {exc}")
                continue

            if result.status == "candidate":
                candidates.append(result)
                print(f"  {ticker:<16} CANDIDATE  (breakout {result.breakout_kind})")
            elif result.status == "rejected":
                rejected.append(result)
            elif result.status == "no_levels":
                no_levels_tickers.append(ticker)
            elif result.status == "insufficient_history":
                insufficient_tickers.append(ticker)
            elif result.status == "stale":
                stale_tickers.append(ticker)

            if i % 100 == 0:
                print(f"  ... {i}/{len(tickers)} screened")
    finally:
        read_conn.close()

    # SQLite-FIRST: persist the durable artifact before touching Obsidian.
    write_conn = sqlite3.connect(DB_PATH)
    try:
        require_tables(write_conn, REQUIRED_TABLES)
        save_candidates(write_conn, scan_date, candidates)

        obsidian_status, obsidian_message = "skipped", None
        if use_obsidian:
            api_key = os.environ.get("OBSIDIAN_API_KEY")
            host = os.environ.get("OBSIDIAN_HOST", "localhost")
            if not api_key:
                obsidian_status = "skipped"
                obsidian_message = "OBSIDIAN_API_KEY not set"
            else:
                note = build_scan_note(
                    scan_date,
                    candidates,
                    rejected,
                    {
                        "total": len(tickers),
                        "scanned": len(tickers) - errors_count,
                        "no_levels": len(no_levels_tickers),
                        "no_levels_tickers": no_levels_tickers,
                        "insufficient": len(insufficient_tickers),
                        "insufficient_tickers": insufficient_tickers,
                        "stale": len(stale_tickers),
                        "stale_tickers": stale_tickers,
                        "errors": errors_count,
                    },
                )
                ok, msg = save_to_obsidian(note, scan_date, api_key, host)
                obsidian_status = "saved" if ok else "failed"
                obsidian_message = msg

        status = "partial" if errors_count else "success"
        log_run(
            write_conn,
            scan_date=scan_date,
            total=len(tickers),
            scanned=len(tickers) - errors_count,
            candidates=len(candidates),
            no_levels=len(no_levels_tickers),
            insufficient=len(insufficient_tickers),
            stale=len(stale_tickers),
            errors=errors_count,
            obsidian_status=obsidian_status,
            obsidian_message=obsidian_message,
            status=status,
            duration=time.monotonic() - start,
        )
    finally:
        write_conn.close()

    # Summary
    print("\n" + "=" * 50)
    print(f"Candidates: {len(candidates)}")
    print(f"Rejected:   {len(rejected)}")
    print(f"No levels:  {len(no_levels_tickers)}")
    print(f"Insufficient history: {len(insufficient_tickers)}")
    print(f"Stale:      {len(stale_tickers)}")
    print(f"Errors:     {errors_count}")
    print(f"Obsidian:   {obsidian_status}" + (f" — {obsidian_message}" if obsidian_message else ""))
    print(f"Saved to SQLite scan_results (scan_date={scan_date}).")
    if obsidian_status == "failed":
        print("NOTE: Obsidian write FAILED — results are safe in SQLite.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily NSE batch screener.")
    parser.add_argument(
        "--limit", type=int, default=None, help="Screen only the first N active tickers (testing)."
    )
    parser.add_argument(
        "--no-obsidian", action="store_true", help="Skip the Obsidian write entirely."
    )
    args = parser.parse_args()
    run_screen(limit=args.limit, use_obsidian=not args.no_obsidian)


if __name__ == "__main__":
    main()
