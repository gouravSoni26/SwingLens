# AI role: research support only — never generates trade signals, predictions, or confidence scores
"""Daily research-brief generator for the NSE Trading Analyst pipeline.

For every ticker in today's ``scan_results`` this script reads the precomputed
indicator row from ``indicator_snapshots``, asks Groq Llama 3.3 70B to write a
factual, multi-timeframe narrative brief (one call per ticker, sequential), then
persists the result SQLite-first (the ``analyses`` table) and, as a best-effort
secondary sink, writes one aggregate note to the Obsidian vault.

Modes:

    Default (no args) : brief every ticker in today's ``scan_results``
                        (scan_date = today). Zero candidates => clean exit 0.
    Manual (--ticker) : brief one ticker directly off its stored indicator
                        snapshot, bypassing ``scan_results`` (mirrors
                        analyze.py --ticker). Exit 1 if no snapshot exists.

The brief is purely descriptive. A governance word-scanner runs over every Groq
response: if any forbidden directional word is found the brief is flagged with a
``[GOVERNANCE FLAG]`` marker and a WARNING is logged, but the brief is still
persisted — the flag is the audit trail, never a silent drop.

Provider provenance
-------------------
- Groq Llama 3.3 70B (``llama-3.3-70b-versatile``) is the only provider here
  (CLAUDE.md AI model split: Groq is the fallback; the brief pipeline uses it
  directly to keep this batch job off the metered Claude path).
- Low temperature keeps the narrative grounded in the supplied numeric values.

RESEARCH SUPPORT ONLY. This script produces descriptive narrative for manual
review. It never emits buy/sell signals, predictions, confidence scores, or
order suggestions (CLAUDE.md governance constraints).

Schema source of truth: docs/phase3-schema.md + scripts/init_db.py + storage.py
Usage:
    python scripts/brief.py                 # today's scan candidates
    python scripts/brief.py --date 2026-06-19   # a specific scan_date
    python scripts/brief.py --ticker RELIANCE.NS  # one ticker, off its snapshot
    python scripts/brief.py --no-obsidian       # skip the Obsidian write
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import ssl
import sys
import urllib.request
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Load .env so GROQ_API_KEY / OBSIDIAN_API_KEY (and OBSIDIAN_HOST) are available
# when this script runs standalone, e.g. from Task Scheduler. Mirrors screen.py.
load_dotenv()

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "analyses.db"

# ── Groq parameters ───────────────────────────────────────────────────────────
GROQ_MODEL = "llama-3.3-70b-versatile"  # CLAUDE.md AI model split
GROQ_MAX_TOKENS = 1200
GROQ_TEMPERATURE = 0.1  # low = grounded, consistent narrative

# Cap the per-run workload. Today's candidate list should be small; a much larger
# list signals an upstream problem, so truncate (with a warning) rather than fan
# out an unbounded number of metered Groq calls.
MAX_BRIEF_TICKERS = 20

OBSIDIAN_VAULT_FOLDER = "08-Daily-Logs"
OBSIDIAN_HEADER = "Research support only. Not a trade signal. No buy/sell recommendation."

# Marker appended to any brief whose text contains forbidden directional language.
GOVERNANCE_FLAG = "[GOVERNANCE FLAG]"

# Forbidden directional vocabulary (CLAUDE.md: no signals/predictions/direction).
# Multi-word phrases are matched as phrases; single words are matched on word
# boundaries so "buy" never trips on "buyer". All matching is case-insensitive.
FORBIDDEN_WORDS = (
    "suggests",
    "implies",
    "indicates direction",
    "supports",
    "expects",
    "likely",
    "momentum building",
    "breakout expected",
    "continuation",
    "reversal",
    "forecast",
    "prediction",
    "signal",
    "buy",
    "sell",
    "recommend",
)

# Precompiled, word-boundary, case-insensitive matchers (one per forbidden term).
_FORBIDDEN_PATTERNS = tuple(
    (word, re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)) for word in FORBIDDEN_WORDS
)

# Snapshot columns fed into the prompt (mirrors analyze.SNAPSHOT_COLUMNS, read
# side). indicator_snapshots already stores 2-decimal-rounded values, so no
# rounding happens here — the brief reports the stored numbers verbatim.
SNAPSHOT_READ_COLUMNS = [
    "ticker",
    "analysis_date",
    "latest_close",
    "latest_date",
    "daily_sma50",
    "daily_sma200",
    "daily_rsi14",
    "daily_macd",
    "daily_macd_signal",
    "daily_macd_hist",
    "daily_bb_upper",
    "daily_bb_mid",
    "daily_bb_lower",
    "weekly_sma20",
    "weekly_sma50",
    "weekly_rsi14",
    "weekly_macd",
    "weekly_macd_signal",
    "weekly_macd_hist",
    "weekly_bb_upper",
    "weekly_bb_mid",
    "weekly_bb_lower",
    "monthly_sma20",
    "monthly_rsi14",
    "monthly_macd",
    "monthly_macd_signal",
    "monthly_macd_hist",
    "monthly_bb_upper",
    "monthly_bb_mid",
    "monthly_bb_lower",
    "vol_daily",
    "vol_sma_20",
    "vol_ratio",
]


# ── Data access (read side) ───────────────────────────────────────────────────


def select_brief_tickers(conn: sqlite3.Connection, scan_date: str) -> list[str]:
    """Distinct tickers in scan_results for scan_date, capped at MAX_BRIEF_TICKERS.

    A list longer than the cap is truncated (a WARNING is logged) so one run can
    never fan out an unbounded number of Groq calls.
    """
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM scan_results WHERE scan_date = ? ORDER BY ticker",
        (scan_date,),
    ).fetchall()
    tickers = [r[0] for r in rows]
    if len(tickers) > MAX_BRIEF_TICKERS:
        logger.warning(
            "scan_results has %d candidates for %s; truncating to MAX_BRIEF_TICKERS=%d",
            len(tickers),
            scan_date,
            MAX_BRIEF_TICKERS,
        )
        tickers = tickers[:MAX_BRIEF_TICKERS]
    return tickers


def load_snapshot(conn: sqlite3.Connection, ticker: str, analysis_date: str) -> dict | None:
    """Read the indicator_snapshots row for (ticker, analysis_date) as a dict.

    Returns None if no snapshot exists — the brief cannot be written without the
    indicators it is supposed to describe, so the caller treats this as an error
    for that ticker (never a fabricated brief).
    """
    col_list = ", ".join(SNAPSHOT_READ_COLUMNS)
    row = conn.execute(
        f"SELECT {col_list} FROM indicator_snapshots WHERE ticker = ? AND analysis_date = ?",
        (ticker, analysis_date),
    ).fetchone()
    if row is None:
        return None
    return {col: row[col] for col in SNAPSHOT_READ_COLUMNS}


# ── Prompt construction ───────────────────────────────────────────────────────


def build_system_prompt() -> str:
    """Governance-constrained system prompt: factual description, no direction.

    The model is told to walk the timeframes in methodology order (monthly →
    weekly → daily) and describe each indicator's stored value without any
    directional interpretation. The forbidden vocabulary is listed explicitly.
    """
    forbidden = ", ".join(FORBIDDEN_WORDS)
    return (
        "You are a research-support assistant for an NSE swing-trading journal. "
        "Your only job is to describe the supplied technical-indicator values in "
        "plain language for a human analyst to review.\n\n"
        "HARD RULES:\n"
        "1. Describe ONLY the numeric values provided. Do not infer, interpret, "
        "or state any market direction, outlook, or what a value means for "
        "future price.\n"
        "2. Never produce a trade idea, entry, exit, target, stop, or any "
        "recommendation. This is not a trade signal.\n"
        "3. Do NOT use any of these words or phrases: "
        f"{forbidden}.\n"
        "4. Walk the timeframes in this order, one short paragraph each: "
        "Monthly, then Weekly, then Daily. Within each, state the SMA, RSI, "
        "MACD, and Bollinger Band values factually. Refer to the MACD signal "
        "line as the 'trigger line' — do not use the word 'signal' anywhere.\n"
        "5. Close with a one-line factual recap of the latest close and date. "
        "No conclusion about what to do.\n\n"
        "Write in calm, neutral, descriptive prose. Report numbers, not opinions."
    )


def _v(value: object) -> str:
    """Render a stored numeric value for the prompt; None becomes 'N/A'."""
    return "N/A" if value is None else str(value)


def _vc(value: object) -> str:
    """Render a numeric value with thousands separators; None becomes 'N/A'."""
    return "N/A" if value is None else f"{value:,}"


def build_user_message(snapshot: dict) -> str:
    """Lay out the stored indicator values as a flat, factual block.

    No interpretation here either — the user message is pure data so the model
    has nothing to do but describe it.
    """
    s = snapshot
    return (
        f"Ticker: {s['ticker']}\n"
        f"Analysis date: {s['analysis_date']}\n"
        f"Latest close: {_v(s['latest_close'])} (as of {_v(s['latest_date'])})\n\n"
        "MONTHLY\n"
        f"  SMA20: {_v(s['monthly_sma20'])}\n"
        f"  RSI14: {_v(s['monthly_rsi14'])}\n"
        f"  MACD line/trigger/hist: {_v(s['monthly_macd'])} / "
        f"{_v(s['monthly_macd_signal'])} / {_v(s['monthly_macd_hist'])}\n"
        f"  Bollinger upper/mid/lower: {_v(s['monthly_bb_upper'])} / "
        f"{_v(s['monthly_bb_mid'])} / {_v(s['monthly_bb_lower'])}\n\n"
        "WEEKLY\n"
        f"  SMA20/SMA50: {_v(s['weekly_sma20'])} / {_v(s['weekly_sma50'])}\n"
        f"  RSI14: {_v(s['weekly_rsi14'])}\n"
        f"  MACD line/trigger/hist: {_v(s['weekly_macd'])} / "
        f"{_v(s['weekly_macd_signal'])} / {_v(s['weekly_macd_hist'])}\n"
        f"  Bollinger upper/mid/lower: {_v(s['weekly_bb_upper'])} / "
        f"{_v(s['weekly_bb_mid'])} / {_v(s['weekly_bb_lower'])}\n\n"
        "DAILY\n"
        f"  SMA50/SMA200: {_v(s['daily_sma50'])} / {_v(s['daily_sma200'])}\n"
        f"  RSI14: {_v(s['daily_rsi14'])}\n"
        f"  MACD line/trigger/hist: {_v(s['daily_macd'])} / "
        f"{_v(s['daily_macd_signal'])} / {_v(s['daily_macd_hist'])}\n"
        f"  Bollinger upper/mid/lower: {_v(s['daily_bb_upper'])} / "
        f"{_v(s['daily_bb_mid'])} / {_v(s['daily_bb_lower'])}\n"
        f"  Volume ratio (today vs 20d avg): {_v(s['vol_ratio'])}  "
        f"({_vc(s['vol_daily'])} vs avg {_vc(s['vol_sma_20'])})\n"
    )


# ── Provider: Groq ─────────────────────────────────────────────────────────────


def call_groq(system_prompt: str, user_msg: str) -> str:
    """Call Groq Llama 3.3 70B for one ticker. Returns the narrative text.

    Mirrors analyzer._call_groq (lazy import, OpenAI-compatible API, low temp).
    Raises on failure — the caller isolates a failing ticker so one bad call
    never aborts the whole run.
    """
    try:
        import groq as groq_sdk
    except ImportError as exc:
        raise ImportError("groq package not installed. Run: pip install groq") from exc

    client = groq_sdk.Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=GROQ_TEMPERATURE,
        max_tokens=GROQ_MAX_TOKENS,
    )
    usage = response.usage
    print(
        f"[Groq]   model={GROQ_MODEL} | "
        f"input={usage.prompt_tokens} | output={usage.completion_tokens}"
    )
    return response.choices[0].message.content.strip()


# ── Governance scan ───────────────────────────────────────────────────────────


def scan_forbidden(text: str) -> list[str]:
    """Return the forbidden words/phrases present in text (case-insensitive).

    Order matches FORBIDDEN_WORDS; each term appears at most once. An empty list
    means the brief is clean.
    """
    return [word for word, pattern in _FORBIDDEN_PATTERNS if pattern.search(text)]


def apply_governance(brief_text: str) -> tuple[str, list[str]]:
    """Scan a brief, log + flag it if needed, and return (final_text, found).

    A flagged brief gets a GOVERNANCE_FLAG header prepended so the marker is
    visible in both SQLite and Obsidian. The brief is never dropped.
    """
    found = scan_forbidden(brief_text)
    if not found:
        return brief_text, found
    logger.warning("governance: forbidden language in brief: %s", ", ".join(found))
    flagged = f"{GOVERNANCE_FLAG} forbidden language detected: {', '.join(found)}\n\n{brief_text}"
    return flagged, found


# ── Persistence (SQLite first — delete-then-insert, idempotent per Decision A) ──


def save_brief(conn: sqlite3.Connection, row: dict) -> None:
    """Replace today's brief for (ticker, analysis_date), then insert the new one.

    The analyses table has no UNIQUE(ticker, analysis_date) constraint, so this
    mirrors screen.save_candidates: DELETE the existing row then INSERT — a
    re-run overwrites rather than duplicating. The *_view columns are left NULL
    (Decision B); this pipeline only fills narrative/governance_overall/raw_json.

    The DELETE and INSERT run inside a single ``with conn:`` transaction so a
    failed INSERT rolls the DELETE back — the prior row is never left deleted
    without its replacement (matters because this is called per-ticker in a loop
    where a later ticker's commit would otherwise flush an orphaned DELETE).
    """
    with conn:
        conn.execute(
            "DELETE FROM analyses WHERE ticker = ? AND analysis_date = ?",
            (row["ticker"], row["analysis_date"]),
        )
        conn.execute(
            """
            INSERT INTO analyses (ticker, analysis_date, governance_overall, narrative, raw_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["ticker"],
                row["analysis_date"],
                row["governance_overall"],
                row["narrative"],
                row["raw_json"],
            ),
        )


def build_brief_row(snapshot: dict, brief_text: str, found: list[str]) -> dict:
    """Assemble the analyses row dict for one ticker (Decision B mapping)."""
    return {
        "ticker": snapshot["ticker"],
        "analysis_date": snapshot["analysis_date"],
        "governance_overall": "flagged" if found else "clean",
        "narrative": brief_text,
        "raw_json": json.dumps(
            {
                "source": "brief.py",
                "model": GROQ_MODEL,
                "inputs": snapshot,
                "brief": brief_text,
                "forbidden_words": found,
            }
        ),
    }


# ── Obsidian (best-effort secondary sink) ─────────────────────────────────────


def build_obsidian_note(scan_date: str, rows: list[dict]) -> str:
    """Render all briefs for the day as one markdown note. Research support only."""
    lines = [
        "---",
        f"date: {scan_date}",
        "type: daily-brief",
        "tags:",
        "  - trading",
        "  - daily-brief",
        "---",
        "",
        f"# Daily Research Brief — {scan_date}",
        "",
        f"> {OBSIDIAN_HEADER}",
        "",
        f"{len(rows)} ticker(s) briefed.",
        "",
    ]
    for row in rows:
        flag = " — ⚠ GOVERNANCE FLAG" if row["governance_overall"] == "flagged" else ""
        lines += [
            f"## {row['ticker']}{flag}",
            "",
            row["narrative"],
            "",
            "---",
            "",
        ]
    lines += [
        "*Generated by NSE Trading Analyst · scripts/brief.py · Paper trading only*",
    ]
    return "\n".join(lines)


def save_to_obsidian(
    note: str, scan_date: str, api_key: str, host: str = "localhost"
) -> tuple[bool, str]:
    """PUT the day's brief note into the Obsidian vault via the Local REST API.

    Mirrors the stdlib urllib + self-signed-cert transport used by storage.py.
    Returns (success, message); never raises — the caller treats Obsidian as a
    best-effort secondary sink after SQLite has already been written.
    """
    path = f"{OBSIDIAN_VAULT_FOLDER}/{scan_date}-brief.md"
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


# ── Orchestration ──────────────────────────────────────────────────────────────


def run(
    scan_date: str | None = None,
    ticker: str | None = None,
    use_obsidian: bool = True,
    db_path: Path = DB_PATH,
) -> int:
    """Entry point for both modes. Returns a process exit code (0 = ok, 1 = errors).

    Default mode (ticker=None): brief every ticker in today's scan_results.
    Manual mode (ticker set): brief that one ticker directly off its stored
    indicator snapshot, bypassing scan_results (mirrors analyze.py --ticker).
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}. Run scripts/init_db.py first.")

    scan_date = scan_date or date.today().isoformat()
    if not os.environ.get("GROQ_API_KEY"):
        # Groq is the only provider for the brief; never silently fabricate.
        print("GROQ_API_KEY not set — cannot generate briefs. Aborting.")
        return 1

    system_prompt = build_system_prompt()
    obsidian_key = os.environ.get("OBSIDIAN_API_KEY")
    obsidian_host = os.environ.get("OBSIDIAN_HOST", "localhost")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if ticker:
            # Manual mode: brief one ticker off its stored snapshot, bypassing
            # scan_results. Normalize so 'reliance.ns' matches the stored
            # 'RELIANCE.NS' (same CLI boundary pattern as analyze.py).
            ticker = ticker.strip().upper()
            print(f"Manual mode: generating brief for {ticker}")
            if load_snapshot(conn, ticker, scan_date) is None:
                print(
                    f"No indicator snapshot for {ticker} on {scan_date} — "
                    f"run analyze.py --ticker {ticker} first"
                )
                return 1
            tickers = [ticker]
        else:
            tickers = select_brief_tickers(conn, scan_date)
            if not tickers:
                print("0 candidates for today, exiting cleanly")
                return 0
            print(f"Briefing {len(tickers)} candidate(s) for {scan_date}")

        saved_rows: list[dict] = []
        errors = 0
        for ticker in tickers:
            try:
                snapshot = load_snapshot(conn, ticker, scan_date)
                if snapshot is None:
                    errors += 1
                    print(f"  {ticker:<16} ERROR: no indicator snapshot for {scan_date}")
                    continue
                brief_text = call_groq(system_prompt, build_user_message(snapshot))
                final_text, found = apply_governance(brief_text)
                row = build_brief_row(snapshot, final_text, found)
                save_brief(conn, row)  # SQLite first — must succeed
                saved_rows.append(row)
                flag = " [FLAGGED]" if found else ""
                print(f"  {ticker:<16} brief saved{flag}")
            except Exception as exc:  # noqa: BLE001 — isolate one bad ticker
                errors += 1
                print(f"  {ticker:<16} ERROR: {exc}")

        # Obsidian: best-effort, single aggregate note, only after SQLite writes.
        # Wrapped so even an unexpected raise can never undo the committed rows.
        if use_obsidian and saved_rows:
            if not obsidian_key:
                print("Obsidian skipped — OBSIDIAN_API_KEY not set")
            else:
                try:
                    note = build_obsidian_note(scan_date, saved_rows)
                    ok, message = save_to_obsidian(note, scan_date, obsidian_key, obsidian_host)
                except Exception as exc:  # noqa: BLE001 — Obsidian never blocks SQLite
                    ok, message = False, str(exc)
                status = "saved" if ok else "failed"
                print(f"Obsidian {status} — {message}")
                if not ok:
                    print("NOTE: Obsidian write FAILED — briefs are safe in SQLite.")

        if errors:
            print(f"\nCompleted with {errors} error(s).")
            return 1
        return 0
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Daily Groq research-brief generator (research support only)."
    )
    parser.add_argument(
        "--date",
        help="scan_date to brief (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--ticker",
        help="Generate brief for this ticker directly, bypassing scan_results.",
    )
    parser.add_argument(
        "--no-obsidian", action="store_true", help="Skip the Obsidian write entirely."
    )
    args = parser.parse_args()
    sys.exit(run(scan_date=args.date, ticker=args.ticker, use_obsidian=not args.no_obsidian))


if __name__ == "__main__":
    main()
