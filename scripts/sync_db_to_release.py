"""GitHub Releases DB sync — push side for the NSE Trading Analyst pipeline.

Uploads ``data/analyses.db`` to a single rolling GitHub Release (tag
``RELEASE_TAG``) so the deployed Streamlit Community Cloud app (no persistent
storage) can fetch it on cold start (see ``db_sync.py`` for the pull side).
Replaces the old git-push sync, which closed when ``data/analyses.db`` was
untracked from git per CLAUDE.md's "never commit data/analyses.db" rule.

Called from the tail of ``scripts/brief.py``'s ``run()`` as a best-effort step
(mirrors its Obsidian secondary-sink pattern) — NOT a separate Task Scheduler
job. The 4 pipeline jobs (fetch_ohlcv/screen/analyze/brief) are independent,
wall-clock-triggered Task Scheduler tasks, not completion-chained; a 5th job at
a fixed time could race a slow brief.py run. Folding the sync into brief.py's
own tail ties it to actual completion instead.

Every attempt (success or failure) is logged to ``db_sync_log`` — Task
Scheduler captures no stdout/stderr for these jobs and its own event log is
disabled on this machine, so a print alone would vanish. The DB row is the
durable, queryable record.

venv python only: D:\\nse-trading-analyst\\trading-app\\Scripts\\python.exe
Usage:
    python scripts/sync_db_to_release.py                # sync data/analyses.db
    python scripts/sync_db_to_release.py --db-path X.db  # override, for tests/dry-run
"""

import argparse
import logging
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "analyses.db"

RELEASE_TAG = "data-latest"
RELEASE_TITLE = "Latest DB sync"
RELEASE_NOTES = "Auto-updated by pipeline"
GH_TIMEOUT_SECONDS = 120  # 82MB upload over a home connection — generous budget


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    """Run a `gh` subcommand from REPO_ROOT so it infers the repo from the git
    remote. Raises FileNotFoundError if `gh` itself isn't on PATH — the caller
    turns that into a clear message rather than a bare traceback.
    """
    return subprocess.run(
        ["gh", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
    )


def release_exists(tag: str = RELEASE_TAG) -> bool:
    """True if a release with this tag already exists (exit 0 on `gh release view`)."""
    result = _run_gh(["release", "view", tag])
    return result.returncode == 0


def upload_db_to_release(db_path: Path, tag: str = RELEASE_TAG) -> tuple[bool, str]:
    """Create the release (bootstrap) or clobber-upload the asset (every run
    after). Never raises — subprocess/timeout/missing-binary failures are
    caught and reported as (False, message).
    """
    if not db_path.exists():
        return False, f"DB not found at {db_path}"

    try:
        if release_exists(tag):
            result = _run_gh(["release", "upload", tag, str(db_path), "--clobber"])
        else:
            result = _run_gh(
                ["release", "create", tag, "--title", RELEASE_TITLE, "--notes", RELEASE_NOTES, str(db_path)]
            )
    except FileNotFoundError:
        return False, "gh CLI not found on PATH — install it (https://cli.github.com) and run `gh auth login`"
    except subprocess.TimeoutExpired:
        return False, f"gh command timed out after {GH_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001 — best-effort; report, never crash the caller
        return False, str(exc)

    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "gh exited non-zero").strip()
    return True, f"Uploaded {db_path.name} to release {tag}"


def _log_sync_attempt(db_path: Path, status: str, message: str, duration_seconds: float) -> None:
    """Best-effort write to db_sync_log inside db_path itself — a logging
    failure must never mask the sync result, so this never raises out to the
    caller. Writes nowhere (never falls back to the production DB) if db_path
    doesn't exist — a test passing a missing temp path must not accidentally
    log into the real data/analyses.db.
    """
    if not db_path.exists():
        print(f"db_sync_log skipped — {db_path} does not exist")
        return
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO db_sync_log (status, message, db_size_bytes, duration_seconds) "
                "VALUES (?, ?, ?, ?)",
                (status, message, db_path.stat().st_size, duration_seconds),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — logging is best-effort, never fatal
        print(f"WARNING: could not write db_sync_log row: {exc}")


def sync_db_to_release(db_path: Path = DB_PATH, tag: str = RELEASE_TAG) -> tuple[bool, str]:
    """Upload db_path to the release, log the attempt, and return (ok, message).

    Never raises — mirrors analyze.py/brief.py's save_to_obsidian contract so
    callers (e.g. brief.py's run()) can treat this as a best-effort tail step.
    """
    start = time.monotonic()
    ok, message = upload_db_to_release(db_path, tag)
    duration = time.monotonic() - start
    status = "success" if ok else "failed"
    _log_sync_attempt(db_path, status, message, duration)
    if not ok:
        logger.warning("db_sync_to_release failed: %s", message)
    return ok, message


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Upload data/analyses.db to the data-latest GitHub Release (idempotent)."
    )
    parser.add_argument(
        "--db-path",
        default=str(DB_PATH),
        help="Override the DB path (used by tests / dry runs).",
    )
    args = parser.parse_args()

    ok, message = sync_db_to_release(db_path=Path(args.db_path))
    print(f"{'OK' if ok else 'FAILED'}: {message}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
