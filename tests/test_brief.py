"""Unit + integration tests for scripts/brief.py.

Run:  pytest tests/test_brief.py -v

The governance scanner and prompt builders are tested as pure functions. The
orchestration paths (zero-candidate exit, truncation, SQLite-first persistence,
Obsidian-failure isolation, delete-then-insert idempotency) run against a
temporary on-disk SQLite DB seeded with synthetic snapshots. Groq is always
monkeypatched — no network, ever.
"""

import json
import logging
import sqlite3
import sys
from pathlib import Path

import pytest

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import brief  # noqa: E402
import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network_feeds(monkeypatch):
    """No network in unit tests — stub the RSS fetch (mirrors the Groq stub).

    run() now calls brief.fetch_news_context per ticker; without this the
    run()-based tests would hit live feeds. Returns the no-feed fallback so the
    prompt path is exercised without any HTTP.
    """
    monkeypatch.setattr(
        brief, "fetch_news_context", lambda ticker, sector=None: brief.NO_FEED_FALLBACK
    )


# ── 1. Governance scanner ─────────────────────────────────────────────────────


def test_scan_forbidden_detects_each_word():
    for word in brief.FORBIDDEN_WORDS:
        text = f"The chart {word} something about the data."
        assert word in brief.scan_forbidden(text), f"{word!r} not detected"


def test_scan_forbidden_is_case_insensitive():
    assert brief.scan_forbidden("This SIGNAL is strong") == ["signal"]


def test_scan_forbidden_clean_text_returns_empty():
    clean = "The daily RSI value is 54.2 and the SMA50 is 1432.10."
    assert brief.scan_forbidden(clean) == []


def test_scan_forbidden_respects_word_boundaries():
    # "buyer" / "seller" must NOT trip the 'buy' / 'sell' matchers.
    assert brief.scan_forbidden("The buyer met the seller.") == []


def test_scan_forbidden_detects_multiword_phrase():
    assert "momentum building" in brief.scan_forbidden("There is momentum building here.")


# ── 2. apply_governance flags but never drops ─────────────────────────────────


def test_apply_governance_clean_passes_through():
    text = "RSI is 50. MACD line is 1.2."
    final, found = brief.apply_governance(text)
    assert found == []
    assert final == text
    assert brief.GOVERNANCE_FLAG not in final


def test_apply_governance_flags_forbidden_text(caplog):
    text = "This is a buy signal."
    with caplog.at_level(logging.WARNING):
        final, found = brief.apply_governance(text)
    assert set(found) == {"buy", "signal"}
    assert final.startswith(brief.GOVERNANCE_FLAG)
    assert text in final  # original brief preserved, never dropped
    assert "forbidden language" in caplog.text


# ── 3. Prompt builders are themselves clean ───────────────────────────────────


def test_system_prompt_lists_forbidden_words():
    prompt = brief.build_system_prompt()
    for word in brief.FORBIDDEN_WORDS:
        assert word in prompt


def test_user_message_contains_factual_values_and_no_forbidden_words():
    snapshot = _snapshot("TEST.NS", "2026-06-19")
    msg = brief.build_user_message(snapshot)
    assert "1500.0" in msg  # latest_close rendered
    assert "RSI14" in msg
    # Our own prompt must not contain forbidden directional language.
    assert brief.scan_forbidden(msg) == []


# ── Temp-DB scaffolding ───────────────────────────────────────────────────────


def _snapshot(ticker: str, analysis_date: str) -> dict:
    """A fully-populated snapshot dict matching SNAPSHOT_READ_COLUMNS."""
    base = {col: 1.0 for col in brief.SNAPSHOT_READ_COLUMNS}
    base["ticker"] = ticker
    base["analysis_date"] = analysis_date
    base["latest_close"] = 1500.0
    base["latest_date"] = analysis_date
    return base


def _make_db(tmp_path: Path, scan_date: str, seed_ticker: str | None = None) -> str:
    """Temp DB with the tables brief.py touches; optionally seed one candidate."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    try:
        init_db.init_indicator_snapshots(conn)  # real schema, stays in sync
        conn.execute(
            "CREATE TABLE scan_results (scan_date DATE, ticker TEXT, "
            "latest_date DATE, latest_close REAL)"
        )
        # Mirror the analyses table created by storage.py (no unique constraint).
        conn.execute(
            """
            CREATE TABLE analyses (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker             TEXT NOT NULL,
                analysis_date      TEXT NOT NULL,
                monthly_view       TEXT,
                weekly_view        TEXT,
                daily_view         TEXT,
                h1_view            TEXT,
                alignment_summary  TEXT,
                governance_overall TEXT,
                narrative          TEXT,
                raw_json           TEXT,
                created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        if seed_ticker:
            conn.execute(
                "INSERT INTO scan_results (scan_date, ticker, latest_date, latest_close) "
                "VALUES (?, ?, ?, ?)",
                (scan_date, seed_ticker, scan_date, 1500.0),
            )
            _seed_snapshot(conn, seed_ticker, scan_date)
        conn.commit()
    finally:
        conn.close()
    return str(db)


def _seed_snapshot(conn: sqlite3.Connection, ticker: str, analysis_date: str) -> None:
    snap = _snapshot(ticker, analysis_date)
    cols = ", ".join(snap.keys())
    placeholders = ", ".join("?" for _ in snap)
    conn.execute(
        f"INSERT INTO indicator_snapshots ({cols}) VALUES ({placeholders})",
        list(snap.values()),
    )


# ── 4. Truncation at MAX_BRIEF_TICKERS ────────────────────────────────────────


def test_select_brief_tickers_truncates_with_warning(tmp_path, caplog):
    scan_date = "2026-06-19"
    db = _make_db(tmp_path, scan_date)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        over = brief.MAX_BRIEF_TICKERS + 5
        conn.executemany(
            "INSERT INTO scan_results (scan_date, ticker, latest_date, latest_close) "
            "VALUES (?, ?, ?, ?)",
            [(scan_date, f"T{i:03d}.NS", scan_date, 100.0) for i in range(over)],
        )
        conn.commit()
        with caplog.at_level(logging.WARNING):
            tickers = brief.select_brief_tickers(conn, scan_date)
    finally:
        conn.close()
    assert len(tickers) == brief.MAX_BRIEF_TICKERS
    assert "truncating" in caplog.text


# ── 5. Zero-candidate default mode exits cleanly ──────────────────────────────


def test_zero_candidates_exits_clean(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    db = _make_db(tmp_path, "2026-06-19")  # scan_results empty
    exit_code = brief.run(scan_date="2026-06-19", use_obsidian=False, db_path=db)
    assert exit_code == 0
    assert "0 candidates for today, exiting cleanly" in capsys.readouterr().out


# ── 6. SQLite-first: Obsidian failure does not block the SQLite write ─────────


def test_obsidian_failure_does_not_block_sqlite(tmp_path, monkeypatch):
    scan_date = "2026-06-19"
    db = _make_db(tmp_path, scan_date, seed_ticker="TEST.NS")

    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    monkeypatch.setenv("OBSIDIAN_API_KEY", "dummy-key")
    monkeypatch.setattr(brief, "call_groq", lambda system, user: "RSI is 50. Factual recap.")

    def boom(*args, **kwargs):
        raise RuntimeError("obsidian down")

    monkeypatch.setattr(brief, "save_to_obsidian", boom)

    # Obsidian raising must not crash the run nor undo the committed SQLite row.
    exit_code = brief.run(scan_date=scan_date, use_obsidian=True, db_path=db)
    assert exit_code == 0

    conn = sqlite3.connect(db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM analyses WHERE ticker = 'TEST.NS'").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


# ── 7. delete-then-insert idempotency — rerun overwrites, never duplicates ─────


def test_rerun_overwrites_no_duplicate(tmp_path, monkeypatch):
    scan_date = "2026-06-19"
    db = _make_db(tmp_path, scan_date, seed_ticker="TEST.NS")

    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    monkeypatch.setattr(brief, "call_groq", lambda system, user: "RSI is 50. Factual recap.")

    brief.run(scan_date=scan_date, use_obsidian=False, db_path=db)
    brief.run(scan_date=scan_date, use_obsidian=False, db_path=db)

    conn = sqlite3.connect(db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM analyses WHERE ticker = 'TEST.NS'").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


# ── 8. Decision B column mapping is persisted ─────────────────────────────────


def test_brief_row_mapping_persisted(tmp_path, monkeypatch):
    scan_date = "2026-06-19"
    db = _make_db(tmp_path, scan_date, seed_ticker="TEST.NS")

    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    monkeypatch.setattr(brief, "call_groq", lambda system, user: "RSI is 50. Factual recap.")

    brief.run(scan_date=scan_date, use_obsidian=False, db_path=db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM analyses WHERE ticker = 'TEST.NS'").fetchone()
    finally:
        conn.close()
    assert row["governance_overall"] == "clean"
    assert row["narrative"] == "RSI is 50. Factual recap."
    assert row["daily_view"] is None  # *_view columns left NULL (Decision B)
    payload = json.loads(row["raw_json"])
    assert payload["source"] == "brief.py"
    assert payload["forbidden_words"] == []


def test_flagged_brief_marks_governance_overall(tmp_path, monkeypatch):
    scan_date = "2026-06-19"
    db = _make_db(tmp_path, scan_date, seed_ticker="TEST.NS")

    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    monkeypatch.setattr(brief, "call_groq", lambda system, user: "This is a buy signal.")

    brief.run(scan_date=scan_date, use_obsidian=False, db_path=db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM analyses WHERE ticker = 'TEST.NS'").fetchone()
    finally:
        conn.close()
    assert row["governance_overall"] == "flagged"
    assert brief.GOVERNANCE_FLAG in row["narrative"]


# ── 9. Missing snapshot is an error, never a fabricated brief ──────────────────


def test_missing_snapshot_is_error(tmp_path, monkeypatch, capsys):
    scan_date = "2026-06-19"
    db = _make_db(tmp_path, scan_date)  # no snapshot seeded
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO scan_results (scan_date, ticker, latest_date, latest_close) "
            "VALUES (?, ?, ?, ?)",
            (scan_date, "NOSNAP.NS", scan_date, 100.0),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    monkeypatch.setattr(brief, "call_groq", lambda system, user: "should never be called")

    exit_code = brief.run(scan_date=scan_date, use_obsidian=False, db_path=db)
    assert exit_code == 1
    assert "no indicator snapshot" in capsys.readouterr().out


# ── 10. Obsidian note carries the required disclaimer header ───────────────────


def test_obsidian_note_has_disclaimer_header():
    rows = [
        {"ticker": "TEST.NS", "governance_overall": "clean", "narrative": "RSI is 50."},
    ]
    note = brief.build_obsidian_note("2026-06-19", rows)
    assert brief.OBSIDIAN_HEADER in note
    assert "TEST.NS" in note


# ── 11. --ticker manual mode ───────────────────────────────────────────────────


def test_ticker_mode_missing_snapshot_errors(tmp_path, monkeypatch, capsys):
    # Manual mode for a ticker with no snapshot must abort with the curated
    # message and exit code 1 — never fabricate a brief.
    scan_date = "2026-06-19"
    db = _make_db(tmp_path, scan_date)  # no snapshot seeded
    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    monkeypatch.setattr(brief, "call_groq", lambda system, user: "should never be called")

    exit_code = brief.run(scan_date=scan_date, ticker="ghost.ns", use_obsidian=False, db_path=db)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert (
        f"No indicator snapshot for GHOST.NS on {scan_date} — "
        f"run analyze.py --ticker GHOST.NS first"
    ) in out


def test_ticker_mode_normalizes_and_briefs(tmp_path, monkeypatch, capsys):
    # Manual mode with a valid snapshot: lowercase input is normalized to the
    # stored uppercase ticker, the pipeline runs, and the brief is persisted.
    scan_date = "2026-06-19"
    db = _make_db(tmp_path, scan_date)  # scan_results empty — ticker mode bypasses it
    conn = sqlite3.connect(db)
    try:
        _seed_snapshot(conn, "RELIANCE.NS", scan_date)
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    monkeypatch.setattr(brief, "call_groq", lambda system, user: "RSI is 50. Factual recap.")

    exit_code = brief.run(scan_date=scan_date, ticker="reliance.ns", use_obsidian=False, db_path=db)

    assert exit_code == 0
    assert "Manual mode: generating brief for RELIANCE.NS" in capsys.readouterr().out

    conn = sqlite3.connect(db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM analyses WHERE ticker = 'RELIANCE.NS'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1  # normalized uppercase row persisted, not 'reliance.ns'
