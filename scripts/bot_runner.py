# AI role: capture transport only — never generates trade signals, predictions, or confidence scores
"""Phase 4 Telegram capture bot for the NSE Trading Analyst (TC-01 .. TC-05).

A single long-running process that turns the analyst's phone into a vault inbox:

    /start        -> confirmation reply (TC-01)
    text message  -> timestamped .md note in 00-Inbox/ (TC-02)
    voice note    -> Groq whisper-large-v3-turbo transcription -> .md note (TC-03)

It runs unattended as a Windows Task Scheduler job triggered at startup (TC-04)
and accepts messages from exactly one chat ID — every other sender is silently
ignored (TC-05).

Design (CLAUDE.md governance + ponytail/YAGNI):
- Pure stdlib transport (urllib + ssl), mirroring storage.save_to_obsidian — the
  Telegram Bot API is plain HTTPS, so no bot framework dependency is added.
- Transcription is Groq-hosted (the GROQ_API_KEY already in .env, reused from
  brief.py). No local Whisper, no torch, no ffmpeg.
- This is a capture pipe only. It never analyses, never emits a trade idea.

Secrets (all from .env):
    TELEGRAM_BOT_TOKEN        from BotFather
    TELEGRAM_ALLOWED_CHAT_ID  the only chat ID accepted
    OBSIDIAN_API_KEY / OBSIDIAN_HOST   Local REST API (shared with storage.py)
    GROQ_API_KEY              transcription (shared with brief.py)

Usage:
    python scripts/bot_runner.py
"""

import logging
import os
import ssl
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Anchored to the script's own location, not CWD — the Task Scheduler job
# launches this with an empty WorkingDirectory (onstart trigger), so a bare
# load_dotenv() would search upward from C:\WINDOWS\system32 and never find
# the project's .env.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

# ── Telegram transport ────────────────────────────────────────────────────────
TELEGRAM_API_BASE = "https://api.telegram.org"
# Long-poll: hold the getUpdates request open this long waiting for a message.
LONG_POLL_TIMEOUT_SECONDS = 30
# The socket timeout MUST exceed the long-poll timeout or every poll would abort.
HTTP_TIMEOUT_SECONDS = LONG_POLL_TIMEOUT_SECONDS + 10
# Sleep after a getUpdates failure before retrying, so a network blip does not
# spin the loop hot.
POLL_ERROR_BACKOFF_SECONDS = 5
# We only care about message updates; cuts noise from edits/reactions/etc.
ALLOWED_UPDATES = '["message"]'
# Telegram getFile only serves files up to 20 MB. Voice notes are far smaller;
# guard anyway so a stray large upload fails cleanly instead of OOMing.
MAX_FILE_BYTES = 20 * 1024 * 1024

# ── Commands & replies ────────────────────────────────────────────────────────
START_COMMAND = "/start"
START_REPLY = (
    "NSE Trading Analyst capture bot is live. "
    "Send a text note or a voice note and it lands in your vault inbox. "
    "Research support only — no trade signals."
)
CAPTURE_OK_REPLY = "Saved to vault inbox."
CAPTURE_FAIL_REPLY = "Capture failed — your note was NOT saved. Check the bot logs."

# ── Groq transcription (shared key with brief.py) ─────────────────────────────
GROQ_TRANSCRIBE_MODEL = "whisper-large-v3-turbo"
VOICE_TEMP_SUFFIX = ".ogg"  # Telegram voice notes are OGG/Opus; Groq accepts them directly.

# ── Obsidian sink (mirrors storage.save_to_obsidian) ──────────────────────────
OBSIDIAN_INBOX_FOLDER = "00-Inbox"
OBSIDIAN_PORT = 27124
OBSIDIAN_HEADER = "Captured via Telegram. Research support only — not a trade signal."


@dataclass(frozen=True)
class Config:
    """Runtime secrets/config, loaded once at startup."""

    bot_token: str
    allowed_chat_id: str
    obsidian_api_key: str
    obsidian_host: str


def load_config() -> Config:
    """Read required secrets from the environment, failing fast if any is missing.

    GROQ_API_KEY is validated lazily inside transcribe_voice (only the voice path
    needs it), so a text-only deployment still starts.
    """
    missing = [
        name
        for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID", "OBSIDIAN_API_KEY")
        if not os.environ.get(name)
    ]
    if missing:
        raise RuntimeError(f"Missing required .env keys: {', '.join(missing)}")
    return Config(
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        allowed_chat_id=os.environ["TELEGRAM_ALLOWED_CHAT_ID"].strip(),
        obsidian_api_key=os.environ["OBSIDIAN_API_KEY"],
        obsidian_host=os.environ.get("OBSIDIAN_HOST", "localhost"),
    )


def is_authorized(chat_id: object, config: Config) -> bool:
    """True only for the single whitelisted chat ID (TC-05).

    Telegram sends chat_id as an int; the .env value is a string — compare as
    strings so the types never silently mismatch.
    """
    return chat_id is not None and str(chat_id) == config.allowed_chat_id


# ── Telegram Bot API (stdlib urllib) ──────────────────────────────────────────


def _tg_call(config: Config, method: str, params: dict) -> dict:
    """POST a Telegram Bot API method (form-encoded) and return the parsed result.

    Raises on transport error or a non-ok Telegram response — callers decide
    whether to isolate the failure (the poll loop) or let it surface (tests).
    """
    import json

    url = f"{TELEGRAM_API_BASE}/bot{config.bot_token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram {method} returned not-ok: {payload}")
    return payload["result"]


def tg_get_updates(config: Config, offset: int | None) -> list[dict]:
    """Long-poll for new message updates since ``offset``."""
    params = {
        "timeout": LONG_POLL_TIMEOUT_SECONDS,
        "allowed_updates": ALLOWED_UPDATES,
    }
    if offset is not None:
        params["offset"] = offset
    return _tg_call(config, "getUpdates", params)


def tg_send_message(config: Config, chat_id: object, text: str) -> None:
    """Send a plain-text reply to a chat."""
    _tg_call(config, "sendMessage", {"chat_id": chat_id, "text": text})


def tg_download_voice(config: Config, file_id: str) -> bytes:
    """Resolve a voice file_id to bytes via getFile + the file download endpoint."""
    file_info = _tg_call(config, "getFile", {"file_id": file_id})
    size = file_info.get("file_size")
    if size is not None and size > MAX_FILE_BYTES:
        raise ValueError(f"voice file too large: {size} bytes (max {MAX_FILE_BYTES})")
    file_path = file_info["file_path"]
    url = f"{TELEGRAM_API_BASE}/file/bot{config.bot_token}/{file_path}"
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        return resp.read()


# ── Transcription (Groq, hosted — no local model/ffmpeg) ──────────────────────


def transcribe_voice(ogg_bytes: bytes) -> str:
    """Transcribe OGG voice bytes via Groq whisper-large-v3-turbo.

    Writes the bytes to a temp .ogg file (Groq uses the filename suffix as a
    format hint), transcribes, and always deletes the temp file. Raises on
    failure — the caller isolates it so one bad note never crashes the bot.
    """
    try:
        import groq as groq_sdk
    except ImportError as exc:  # pragma: no cover - dependency already vendored
        raise ImportError("groq package not installed. Run: pip install groq") from exc

    client = groq_sdk.Groq(api_key=os.environ["GROQ_API_KEY"])
    tmp = tempfile.NamedTemporaryFile(suffix=VOICE_TEMP_SUFFIX, delete=False)
    try:
        tmp.write(ogg_bytes)
        tmp.close()
        with open(tmp.name, "rb") as audio:
            result = client.audio.transcriptions.create(file=audio, model=GROQ_TRANSCRIBE_MODEL)
        return result.text.strip()
    finally:
        os.unlink(tmp.name)


# ── Obsidian inbox sink (mirrors storage.save_to_obsidian transport) ──────────


def build_inbox_note(text: str, kind: str, now: datetime) -> str:
    """Render a captured message as a timestamped markdown note."""
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    return (
        "---\n"
        f"date: {now.strftime('%Y-%m-%d')}\n"
        f"time: {now.strftime('%H:%M:%S')}\n"
        "type: telegram-capture\n"
        "source: telegram\n"
        f"kind: {kind}\n"
        "tags:\n"
        "  - inbox\n"
        "  - telegram\n"
        "---\n\n"
        f"# Telegram capture — {stamp}\n\n"
        f"> {OBSIDIAN_HEADER}\n\n"
        f"{text}\n\n"
        "---\n"
        "*Captured via NSE Trading Analyst · scripts/bot_runner.py · Paper trading only*\n"
    )


def write_inbox_note(
    config: Config, text: str, kind: str, now: datetime | None = None
) -> tuple[bool, str]:
    """PUT a capture note into 00-Inbox/ via the Obsidian Local REST API.

    Mirrors storage.save_to_obsidian: stdlib urllib + self-signed-cert bypass,
    returns (success, message), never raises — the caller reports the result.
    """
    now = now or datetime.now()
    filename = f"{now.strftime('%Y-%m-%d_%H%M%S')}-{kind}.md"
    path = f"{OBSIDIAN_INBOX_FOLDER}/{filename}"
    url = f"https://{config.obsidian_host}:{OBSIDIAN_PORT}/vault/{path}"
    note = build_inbox_note(text, kind, now)
    try:
        req = urllib.request.Request(
            url,
            data=note.encode("utf-8"),
            method="PUT",
            headers={
                "Authorization": f"Bearer {config.obsidian_api_key}",
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
    except Exception as exc:  # noqa: BLE001 - best-effort sink; report, never raise
        return False, str(exc)


# ── Dispatch ──────────────────────────────────────────────────────────────────


def _handle_text(config: Config, chat_id: object, text: str) -> None:
    ok, message = write_inbox_note(config, text, kind="text")
    logger.info("text capture from %s: %s", chat_id, message)
    tg_send_message(config, chat_id, CAPTURE_OK_REPLY if ok else CAPTURE_FAIL_REPLY)


def _handle_voice(config: Config, chat_id: object, voice: dict) -> None:
    ogg_bytes = tg_download_voice(config, voice["file_id"])
    transcript = transcribe_voice(ogg_bytes)
    ok, message = write_inbox_note(config, transcript, kind="voice")
    logger.info("voice capture from %s: %s", chat_id, message)
    tg_send_message(config, chat_id, CAPTURE_OK_REPLY if ok else CAPTURE_FAIL_REPLY)


def handle_update(update: dict, config: Config) -> None:
    """Route one Telegram update. Whitelist first, then /start / voice / text.

    Message types other than text and voice are intentionally ignored (YAGNI —
    only TC-02/TC-03 are in scope). Raises on handler failure; the poll loop
    isolates it so the bot never crashes on one bad message (TC error rule).
    """
    message = update.get("message")
    if not message:
        return
    chat_id = message.get("chat", {}).get("id")
    if not is_authorized(chat_id, config):
        logger.info("ignored message from unauthorized chat %s", chat_id)
        return

    text = message.get("text")
    voice = message.get("voice")

    if text is not None and text.strip().startswith(START_COMMAND):
        tg_send_message(config, chat_id, START_REPLY)
        return
    if voice is not None:
        _handle_voice(config, chat_id, voice)
        return
    if text is not None:
        _handle_text(config, chat_id, text)
        return
    logger.info("ignored unsupported message type from %s", chat_id)


# ── Orchestration ─────────────────────────────────────────────────────────────


def run(config: Config) -> None:
    """Long-poll loop. Never returns under normal operation.

    A getUpdates failure logs, backs off, and retries (the whole process is the
    Task Scheduler unit of restart). Each message is handled in its own
    try/except so one bad message is logged and skipped, never fatal.
    """
    logger.info("bot started — polling for messages from chat %s", config.allowed_chat_id)
    offset: int | None = None
    while True:
        try:
            updates = tg_get_updates(config, offset)
        except Exception as exc:  # noqa: BLE001 - poll failures must never crash the bot
            logger.error("getUpdates failed: %s", exc)
            time.sleep(POLL_ERROR_BACKOFF_SECONDS)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            try:
                handle_update(update, config)
            except Exception as exc:  # noqa: BLE001 - isolate one bad message
                logger.error("handling update %s failed: %s", update.get("update_id"), exc)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    run(load_config())


if __name__ == "__main__":
    main()
