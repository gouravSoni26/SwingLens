"""Unit tests for scripts/bot_runner.py.

Run:  pytest tests/test_bot_runner.py -v

Pure functions (whitelist, note rendering, dispatch) are tested directly. Every
side-effecting boundary — the Telegram API, the Obsidian write, and Groq
transcription — is monkeypatched, so no test ever touches the network. Mirrors
the no-network discipline of tests/test_brief.py.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bot_runner  # noqa: E402

CONFIG = bot_runner.Config(
    bot_token="TESTTOKEN",
    allowed_chat_id="42",
    obsidian_api_key="obsidian-key",
    obsidian_host="localhost",
)

FIXED_NOW = datetime(2026, 6, 29, 14, 30, 0)


def _text_update(text: str, chat_id: int = 42) -> dict:
    return {"update_id": 1, "message": {"message_id": 1, "chat": {"id": chat_id}, "text": text}}


def _voice_update(file_id: str = "VOICE123", chat_id: int = 42) -> dict:
    return {
        "update_id": 2,
        "message": {"message_id": 2, "chat": {"id": chat_id}, "voice": {"file_id": file_id}},
    }


# ── 1. Whitelist (TC-05) ──────────────────────────────────────────────────────


def test_authorized_matches_whitelist_int_vs_str():
    # Telegram int chat id vs the str from .env.
    assert bot_runner.is_authorized(42, CONFIG) is True


def test_unauthorized_chat_rejected():
    assert bot_runner.is_authorized(999, CONFIG) is False


def test_none_chat_rejected():
    assert bot_runner.is_authorized(None, CONFIG) is False


def test_unauthorized_message_is_silently_ignored(monkeypatch):
    # Arrange: any send/write would mean the message was acted on.
    calls = []
    monkeypatch.setattr(bot_runner, "tg_send_message", lambda *a, **k: calls.append("send"))
    monkeypatch.setattr(bot_runner, "write_inbox_note", lambda *a, **k: calls.append("write"))

    # Act
    bot_runner.handle_update(_text_update("hello", chat_id=999), CONFIG)

    # Assert: nothing happened.
    assert calls == []


# ── 2. Inbox note rendering (TC-02) ───────────────────────────────────────────


def test_build_inbox_note_has_frontmatter_and_body():
    note = bot_runner.build_inbox_note("captured words here", kind="text", now=FIXED_NOW)
    assert "type: telegram-capture" in note
    assert "kind: text" in note
    assert "date: 2026-06-29" in note
    assert "time: 14:30:00" in note
    assert "captured words here" in note  # body preserved verbatim (capture, not analysis)


def test_write_inbox_note_targets_inbox_with_bearer(monkeypatch):
    captured = {}

    class _Resp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, *args, **kwargs):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["auth"] = req.headers.get("Authorization")
        return _Resp()

    monkeypatch.setattr(bot_runner.urllib.request, "urlopen", fake_urlopen)

    # Act
    ok, message = bot_runner.write_inbox_note(CONFIG, "note text", kind="text", now=FIXED_NOW)

    # Assert
    assert ok is True
    assert captured["method"] == "PUT"
    assert captured["url"] == ("https://localhost:27124/vault/00-Inbox/2026-06-29_143000-text.md")
    assert captured["auth"] == "Bearer obsidian-key"


def test_write_inbox_note_never_raises_on_transport_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(bot_runner.urllib.request, "urlopen", boom)

    ok, message = bot_runner.write_inbox_note(CONFIG, "x", kind="text", now=FIXED_NOW)
    assert ok is False
    assert "connection refused" in message


# ── 3. Dispatch: /start, text, voice ──────────────────────────────────────────


def test_start_command_sends_confirmation(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        bot_runner, "tg_send_message", lambda cfg, chat, text: sent.update(chat=chat, text=text)
    )
    monkeypatch.setattr(
        bot_runner, "write_inbox_note", lambda *a, **k: pytest.fail("must not write a note")
    )

    bot_runner.handle_update(_text_update("/start"), CONFIG)

    assert sent["chat"] == 42
    assert sent["text"] == bot_runner.START_REPLY


def test_text_message_writes_inbox_note(monkeypatch):
    writes = []
    monkeypatch.setattr(
        bot_runner,
        "write_inbox_note",
        lambda cfg, text, kind: writes.append((text, kind)) or (True, "ok"),
    )
    monkeypatch.setattr(bot_runner, "tg_send_message", lambda *a, **k: None)

    bot_runner.handle_update(_text_update("watch RELIANCE near support"), CONFIG)

    assert writes == [("watch RELIANCE near support", "text")]


def test_voice_message_transcribes_then_writes(monkeypatch):
    monkeypatch.setattr(bot_runner, "tg_download_voice", lambda cfg, file_id: b"OGGDATA")
    monkeypatch.setattr(bot_runner, "transcribe_voice", lambda ogg: "transcribed words")
    writes = []
    monkeypatch.setattr(
        bot_runner,
        "write_inbox_note",
        lambda cfg, text, kind: writes.append((text, kind)) or (True, "ok"),
    )
    monkeypatch.setattr(bot_runner, "tg_send_message", lambda *a, **k: None)

    bot_runner.handle_update(_voice_update(), CONFIG)

    assert writes == [("transcribed words", "voice")]


def test_transcribe_voice_cleans_up_temp_file(monkeypatch):
    """Groq is mocked; assert the temp .ogg is deleted even on the happy path."""
    created = {}

    class _FakeTranscription:
        text = "  hello world  "

    class _FakeAudio:
        class transcriptions:  # noqa: N801 - mirrors groq client shape
            @staticmethod
            def create(file, model):
                created["model"] = model
                created["path"] = file.name
                return _FakeTranscription()

    class _FakeGroq:
        def __init__(self, api_key):
            self.audio = _FakeAudio()

    import types

    fake_module = types.SimpleNamespace(Groq=_FakeGroq)
    monkeypatch.setitem(sys.modules, "groq", fake_module)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    text = bot_runner.transcribe_voice(b"OGGDATA")

    assert text == "hello world"  # stripped
    assert created["model"] == bot_runner.GROQ_TRANSCRIBE_MODEL
    assert not Path(created["path"]).exists()  # temp file removed in finally


# ── 4. Error isolation in the dispatch path ───────────────────────────────────


def test_handler_exception_does_not_escape_run_loop(monkeypatch):
    """A raising handler is logged and skipped — the loop processes the next update."""
    handled = []

    def first_then_stop(config, offset):
        # First poll returns two updates, second poll stops the loop.
        if not handled:
            return [_text_update("boom"), _text_update("ok")]
        raise KeyboardInterrupt  # break out of the infinite loop for the test

    def flaky_handle(update, config):
        if update["message"]["text"] == "boom":
            handled.append("boom")
            raise ValueError("handler blew up")
        handled.append("ok")

    monkeypatch.setattr(bot_runner, "tg_get_updates", first_then_stop)
    monkeypatch.setattr(bot_runner, "handle_update", flaky_handle)

    with pytest.raises(KeyboardInterrupt):
        bot_runner.run(CONFIG)

    # Both updates were dispatched; the ValueError did not abort the batch.
    assert handled == ["boom", "ok"]


# ── 5. Config loading ─────────────────────────────────────────────────────────


def test_load_config_fails_fast_on_missing_keys(monkeypatch):
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID", "OBSIDIAN_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError, match="Missing required .env keys"):
        bot_runner.load_config()


def test_load_config_reads_all_keys(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", " 42 ")  # whitespace trimmed
    monkeypatch.setenv("OBSIDIAN_API_KEY", "okey")
    monkeypatch.setenv("OBSIDIAN_HOST", "127.0.0.1")

    config = bot_runner.load_config()

    assert config.bot_token == "tok"
    assert config.allowed_chat_id == "42"
    assert config.obsidian_host == "127.0.0.1"
