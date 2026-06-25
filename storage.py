"""
storage.py
----------
Two save targets:
  1. SQLite  — local analysis history database
  2. Obsidian — creates a markdown note via Local REST API plugin
"""

import json
import sqlite3
import urllib.request
import ssl
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "analyses.db"


# ── SQLite ─────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create the analyses table if it doesn't exist."""
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker           TEXT    NOT NULL,
                analysis_date    TEXT    NOT NULL,
                monthly_view     TEXT,
                weekly_view      TEXT,
                daily_view       TEXT,
                h1_view          TEXT,
                alignment_summary TEXT,
                governance_overall TEXT,
                narrative        TEXT,
                raw_json         TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def save_to_sqlite(analysis: dict) -> int:
    """Save analysis to SQLite. Returns the new row ID."""
    tf = analysis.get("timeframes", {})
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO analyses (
                ticker, analysis_date,
                monthly_view, weekly_view, daily_view, h1_view,
                alignment_summary, governance_overall, narrative, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis.get("ticker"),
                datetime.now().strftime("%Y-%m-%d"),
                tf.get("monthly", {}).get("view"),
                tf.get("weekly",  {}).get("view"),
                tf.get("daily",   {}).get("view"),
                tf.get("h1",      {}).get("view"),
                analysis.get("alignment_summary"),
                analysis.get("governance_overall"),
                analysis.get("narrative"),
                json.dumps(analysis),
            ),
        )
        return cursor.lastrowid


def get_history(limit: int = 20) -> list[dict]:
    """Return the last N analyses from SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, ticker, analysis_date,
                   monthly_view, weekly_view, daily_view, h1_view,
                   governance_overall, created_at
            FROM analyses
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_by_id(analysis_id: int) -> dict | None:
    """Fetch a full analysis JSON by row ID."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT raw_json FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None


# ── Obsidian ───────────────────────────────────────────────────────────────────

def _build_note(analysis: dict) -> str:
    """Render analysis as a markdown note for Obsidian."""
    ticker = analysis.get("ticker", "UNKNOWN")
    date   = datetime.now().strftime("%Y-%m-%d")
    tf     = analysis.get("timeframes", {})
    risk   = analysis.get("risk", {})
    gov    = analysis.get("governance", {})

    def tf_row(k):
        d = tf.get(k, {})
        return f"| {k.upper():8} | {d.get('trend','—'):30} | {d.get('view','—')} |"

    def risk_val(key, prefix="₹"):
        v = risk.get(key)
        return f"{prefix}{v}" if v is not None else "—"

    def gov_status(key):
        v = gov.get(key, "unknown")
        return "N/A" if v == "not_calculable" else v.upper()

    risk_flag = ""
    if risk.get("risk_pass") is False:
        risk_flag = " ⚠ exceeds 1.5% — reduce position size"

    return f"""---
ticker: {ticker}
date: {date}
type: setup-analysis
governance: {analysis.get("governance_overall", "unknown")}
tags:
  - trading
  - setup-analysis
  - {ticker.lower()}
---

# {ticker} — Setup Analysis — {date}

> Research support only. Not a trade signal.

## Timeframe Alignment

| Timeframe | Trend                          | View    |
|-----------|-------------------------------|---------|
{tf_row("monthly")}
{tf_row("weekly")}
{tf_row("daily")}
{tf_row("h1")}

**Overall:** {analysis.get("alignment_summary", "—")}

## Risk Parameters

| Parameter  | Value                  |
|------------|------------------------|
| Entry      | {risk_val("entry")}    |
| Stop-loss  | {risk_val("sl")}       |
| Target     | {risk_val("target")}   |
| Risk/trade | {risk_val("risk_pct", "")}{("%" if risk.get("risk_pct") is not None else "")}{risk_flag} |
| R : R      | {("1 : " + str(risk.get("rr"))) if risk.get("rr") is not None else "—"} |

## Governance Check

| Rule                   | Status                       |
|------------------------|------------------------------|
| NSE cash equity only   | {gov_status("nse_cash")}     |
| Swing hold period      | {gov_status("swing_period")} |
| Not intraday scalp     | {gov_status("not_intraday")} |
| Risk ≤ 1.5% per trade  | {gov_status("risk_limit")}   |
| No auto-execution      | {gov_status("no_auto")}      |

**Overall: {analysis.get("governance_overall","—").upper().replace("_"," ")}**

## Narrative

{analysis.get("narrative", "—")}

## Missing Information

{chr(10).join("- " + m for m in analysis.get("missing_info", [])) or "None noted."}

## Methodology Notes

> [PENDING: methodology.md] — Indicator analysis to be completed after Saif sir's training notes.

---
*Generated by NSE Trading Analyst · Paper trading only*
"""


def save_to_obsidian(
    analysis: dict,
    api_key: str,
    host: str = "localhost",
    vault_folder: str = "08-Daily-Logs",
) -> tuple[bool, str]:
    """
    Save analysis as a markdown note in the Obsidian vault.

    Returns (success: bool, message: str).
    Requires Obsidian to be open with Local REST API plugin running.
    """
    ticker = analysis.get("ticker", "UNKNOWN")
    date   = datetime.now().strftime("%Y-%m-%d")
    path   = f"{vault_folder}/{date}-scanner.md"
    url    = f"https://{host}:27124/vault/{path}"
    note   = _build_note(analysis)

    try:
        # Build request manually (avoid requests dependency, use stdlib)
        data = note.encode("utf-8")
        req  = urllib.request.Request(
            url,
            data=data,
            method="PUT",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "text/markdown; charset=utf-8",
            },
        )
        # Obsidian Local REST API uses a self-signed cert — skip verification
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE

        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            if resp.status in (200, 201, 204):
                return True, f"Saved to {path}"
            return False, f"Unexpected status {resp.status}"

    except Exception as e:
        return False, str(e)
