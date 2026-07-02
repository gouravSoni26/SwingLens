"""GitHub Releases DB sync — pull side for the deployed Streamlit app.

Streamlit Community Cloud has no persistent storage and deploys from `main`.
Since ``data/analyses.db`` is no longer committed to git (CLAUDE.md: "never
commit data/analyses.db"), the deployed app fetches it from the
``data-latest`` GitHub Release on cold start instead — see
``scripts/sync_db_to_release.py`` for the push side (uploaded from the local
pipeline's ``scripts/brief.py`` tail).

SwingLens is a PUBLIC repo (confirmed via the GitHub API), so the release
asset download needs no auth token — a plain HTTPS GET on the public download
URL works.

Fetches ONLY when ``data/analyses.db`` is missing (cold start) — never on a
warm rerun. ``ensure_db_present()`` is wrapped in ``st.cache_resource`` so it
executes at most once per running app process, regardless of how many times
Streamlit reruns the script on user interaction.

If the fetch fails, this degrades gracefully: it never raises, and every page
already guards on ``table_exists()`` / ``DB_PATH.exists()`` (see
``pages/*.py``, ``storage.init_db()``'s ``CREATE TABLE IF NOT EXISTS``), so a
missing DB shows a friendly "run the pipeline first" message rather than a
crash.
"""

import shutil
import urllib.request
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = REPO_ROOT / "data" / "analyses.db"

GITHUB_OWNER = "gouravSoni26"
GITHUB_REPO = "SwingLens"
RELEASE_TAG = "data-latest"
RELEASE_ASSET_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/{RELEASE_TAG}/analyses.db"
)

FETCH_TIMEOUT_SECONDS = 60


def _fetch_db(dest: Path, url: str = RELEASE_ASSET_URL) -> None:
    """Stream the release asset to dest via an atomic rename — a failed or
    interrupted download never leaves a half-written DB file at dest. Raises
    on any failure; the caller (ensure_db_present) decides how to handle it.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.parent / f"{dest.name}.tmp"
    # url is a fixed module constant, never user input — no SSRF/injection surface.
    with (
        urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response,
        open(tmp_path, "wb") as tmp_file,
    ):
        shutil.copyfileobj(response, tmp_file)
    tmp_path.replace(dest)  # atomic on the same filesystem


@st.cache_resource(show_spinner="Fetching latest data...")
def ensure_db_present(db_path: Path = DB_PATH) -> tuple[bool, str]:
    """Fetch data/analyses.db from the release ONLY if it's missing. Never
    raises — a fetch failure is reported (returned + shown as a warning), not
    propagated, so the app can degrade gracefully.

    st.cache_resource memoizes on db_path — every real call site uses the same
    default, so app.py and all 4 pages hit the same cache entry and this runs
    at most once per app process, not once per page/rerun.
    """
    if db_path.exists():
        return True, "DB already present — no fetch needed"
    try:
        _fetch_db(db_path)
        return True, f"Fetched DB from {RELEASE_ASSET_URL}"
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never crash the app
        message = str(exc)
        st.warning(
            f"Could not fetch the latest data ({message}). "
            "Showing whatever local data is available — some pages may be empty."
        )
        return False, message
