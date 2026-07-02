"""Unit tests for scripts/sync_db_to_release.py (push side of the GitHub
Releases DB sync).

Run:  pytest tests/test_sync_db_to_release.py -v

`gh` is never actually invoked — subprocess.run is monkeypatched with a fake
that inspects the args passed and returns a canned result, mirroring how
tests/test_brief.py stubs Groq. No network, no real release calls.
"""

import subprocess
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import init_db  # noqa: E402
import sync_db_to_release as sdr  # noqa: E402


def _fake_result(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _make_db(tmp_path: Path) -> Path:
    """Real schema (db_sync_log included) via init_db.py — stays in sync."""
    db_path = tmp_path / "test.db"
    sqlite3.connect(db_path).close()
    init_db.init_db(db_path)
    return db_path


# ── release_exists ────────────────────────────────────────────────────────────


def test_release_exists_true_on_zero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _fake_result(0))
    assert sdr.release_exists() is True


def test_release_exists_false_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _fake_result(1, stderr="release not found"))
    assert sdr.release_exists() is False


# ── upload_db_to_release ───────────────────────────────────────────────────────


def test_upload_creates_release_when_absent(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        if args[2] == "view":
            return _fake_result(1)  # doesn't exist yet
        assert args[2] == "create"
        return _fake_result(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, message = sdr.upload_db_to_release(db_path)
    assert ok is True
    assert "create" in calls[1]


def test_upload_clobbers_when_release_exists(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        if args[2] == "view":
            return _fake_result(0)  # already exists
        assert args[2] == "upload"
        assert "--clobber" in args
        return _fake_result(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, message = sdr.upload_db_to_release(db_path)
    assert ok is True
    assert "upload" in calls[1]


def test_upload_fails_when_gh_exits_nonzero(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)

    def fake_run(args, **kw):
        if args[2] == "view":
            return _fake_result(0)
        return _fake_result(1, stderr="HTTP 403: rate limited")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, message = sdr.upload_db_to_release(db_path)
    assert ok is False
    assert "rate limited" in message


def test_upload_fails_cleanly_when_gh_not_installed(tmp_path, monkeypatch):
    """Regression: gh CLI is confirmed absent on this machine (session
    investigation) — this must produce a clear message, never a bare traceback.
    """
    db_path = _make_db(tmp_path)

    def fake_run(args, **kw):
        raise FileNotFoundError("gh not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, message = sdr.upload_db_to_release(db_path)
    assert ok is False
    assert "gh CLI not found" in message


def test_upload_fails_on_timeout(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)

    def fake_run(args, **kw):
        if args[2] == "view":
            return _fake_result(0)
        raise subprocess.TimeoutExpired(cmd="gh", timeout=sdr.GH_TIMEOUT_SECONDS)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, message = sdr.upload_db_to_release(db_path)
    assert ok is False
    assert "timed out" in message


def test_upload_fails_when_db_missing():
    ok, message = sdr.upload_db_to_release(Path("Z:/does/not/exist.db"))
    assert ok is False
    assert "not found" in message


# ── _log_sync_attempt (durable failure marker) ─────────────────────────────────


def test_log_sync_attempt_writes_row(tmp_path):
    db_path = _make_db(tmp_path)
    sdr._log_sync_attempt(db_path, "success", "Uploaded ok", 1.23)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status, message, duration_seconds FROM db_sync_log").fetchone()
    finally:
        conn.close()
    assert row == ("success", "Uploaded ok", 1.23)


def test_log_sync_attempt_never_falls_back_to_production_db(tmp_path):
    """Regression: a missing db_path must never cause a write into the real
    data/analyses.db — this must be a no-op (with a printed notice), not a
    fallback to sdr.DB_PATH.
    """
    missing_path = tmp_path / "does_not_exist.db"
    # Must not raise, and must not touch sdr.DB_PATH (the real production DB).
    sdr._log_sync_attempt(missing_path, "failed", "gh not found", 0.01)
    assert not missing_path.exists()


def test_log_sync_attempt_swallows_write_failure(tmp_path):
    """A DB without db_sync_log (e.g. an old schema) must not crash the caller."""
    db_path = tmp_path / "no_table.db"
    sqlite3.connect(db_path).close()  # empty DB, no tables at all
    sdr._log_sync_attempt(db_path, "success", "ok", 0.1)  # must not raise


# ── sync_db_to_release (top-level orchestration) ────────────────────────────────


def test_sync_db_to_release_success_path(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: _fake_result(0))
    ok, message = sdr.sync_db_to_release(db_path=db_path)
    assert ok is True

    conn = sqlite3.connect(db_path)
    try:
        status = conn.execute("SELECT status FROM db_sync_log").fetchone()[0]
    finally:
        conn.close()
    assert status == "success"


def test_sync_db_to_release_failure_path_still_logs(tmp_path, monkeypatch):
    def fake_run(args, **kw):
        if args[2] == "view":
            return _fake_result(0)
        return _fake_result(1, stderr="boom")

    db_path = _make_db(tmp_path)
    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, message = sdr.sync_db_to_release(db_path=db_path)
    assert ok is False

    conn = sqlite3.connect(db_path)
    try:
        status, msg = conn.execute("SELECT status, message FROM db_sync_log").fetchone()
    finally:
        conn.close()
    assert status == "failed"
    assert "boom" in msg


def test_sync_db_to_release_never_raises(tmp_path, monkeypatch):
    def fake_run(args, **kw):
        raise RuntimeError("completely unexpected failure")

    db_path = _make_db(tmp_path)
    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, message = sdr.sync_db_to_release(db_path=db_path)  # must not raise
    assert ok is False


# ── main() — loud, non-zero exit on failure ────────────────────────────────────


def test_main_exits_zero_on_success(tmp_path, monkeypatch, capsys):
    db_path = _make_db(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: _fake_result(0))
    monkeypatch.setattr(sys, "argv", ["sync_db_to_release.py", "--db-path", str(db_path)])
    with pytest.raises(SystemExit) as exc_info:
        sdr.main()
    assert exc_info.value.code == 0
    assert "OK" in capsys.readouterr().out


def test_main_exits_nonzero_on_failure(tmp_path, monkeypatch, capsys):
    db_path = _make_db(tmp_path)

    def fake_run(args, **kw):
        raise FileNotFoundError("gh not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["sync_db_to_release.py", "--db-path", str(db_path)])
    with pytest.raises(SystemExit) as exc_info:
        sdr.main()
    assert exc_info.value.code == 1
    assert "FAILED" in capsys.readouterr().out
