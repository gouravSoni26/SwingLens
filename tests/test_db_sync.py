"""Unit tests for db_sync.py (pull side of the GitHub Releases DB sync).

Run:  pytest tests/test_db_sync.py -v

urllib.request.urlopen is monkeypatched — no real network call, ever. Every
test uses a unique tmp_path-based db_path so st.cache_resource's global cache
(module-level, persists across the whole pytest session) never returns a
stale result from a previous test.
"""

import io
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db_sync  # noqa: E402


class _FakeResponse:
    """Minimal context-manager stand-in for urlopen()'s return value."""

    def __init__(self, data: bytes):
        self._io = io.BytesIO(data)

    def __enter__(self):
        return self._io

    def __exit__(self, *exc_info):
        return False


def _clear_cache():
    db_sync.ensure_db_present.clear()


# ── _fetch_db (unmemoized core) ─────────────────────────────────────────────


def test_fetch_db_downloads_and_atomic_renames(tmp_path, monkeypatch):
    dest = tmp_path / "analyses.db"
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url, timeout=None: _FakeResponse(b"fake db bytes")
    )
    db_sync._fetch_db(dest)
    assert dest.exists()
    assert dest.read_bytes() == b"fake db bytes"
    assert not (tmp_path / "analyses.db.tmp").exists()  # tmp renamed away, not left behind


def test_fetch_db_leaves_dest_untouched_on_failure(tmp_path, monkeypatch):
    dest = tmp_path / "analyses.db"

    def raise_error(url, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", raise_error)
    try:
        db_sync._fetch_db(dest)
        raised = False
    except urllib.error.URLError:
        raised = True
    assert raised
    assert not dest.exists()  # atomic guarantee: never a half-written DB at dest


# ── ensure_db_present (cached, never-raises wrapper) ────────────────────────


def test_ensure_db_present_noop_when_file_exists(tmp_path, monkeypatch):
    db_path = tmp_path / "analyses.db"
    db_path.write_bytes(b"already here")

    def fail_if_called(*a, **kw):
        raise AssertionError("urlopen must not be called when the file already exists")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    _clear_cache()
    ok, message = db_sync.ensure_db_present(db_path=db_path)
    assert ok is True
    assert db_path.read_bytes() == b"already here"  # untouched


def test_ensure_db_present_fetches_when_missing(tmp_path, monkeypatch):
    db_path = tmp_path / "analyses.db"
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url, timeout=None: _FakeResponse(b"fetched bytes")
    )
    _clear_cache()
    ok, message = db_sync.ensure_db_present(db_path=db_path)
    assert ok is True
    assert db_path.read_bytes() == b"fetched bytes"


def test_ensure_db_present_never_raises_on_fetch_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "analyses.db"

    def raise_error(url, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", raise_error)
    warnings = []
    monkeypatch.setattr(db_sync.st, "warning", lambda msg: warnings.append(msg))
    _clear_cache()

    ok, message = db_sync.ensure_db_present(db_path=db_path)  # must not raise
    assert ok is False
    assert not db_path.exists()
    assert len(warnings) == 1  # degrade gracefully: a visible warning, not a crash


def test_ensure_db_present_is_cached_per_process(tmp_path, monkeypatch):
    """A second call with the same db_path must not re-fetch (st.cache_resource)."""
    db_path = tmp_path / "analyses.db"
    call_count = {"n": 0}

    def counting_urlopen(url, timeout=None):
        call_count["n"] += 1
        return _FakeResponse(b"data")

    monkeypatch.setattr(urllib.request, "urlopen", counting_urlopen)
    _clear_cache()
    db_sync.ensure_db_present(db_path=db_path)
    db_sync.ensure_db_present(db_path=db_path)  # same args -> cache hit, no second fetch
    assert call_count["n"] == 1
