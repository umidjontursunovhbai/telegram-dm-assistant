import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from telegram_dm_assistant.assistant import DMAssistant, DraftStore
from telegram_dm_assistant.config import Config
from telegram_dm_assistant.llm import trim_reply


class Event:
    def __init__(self, sender_id=42, chat_id=42, message_id=7, text="hello", **kw):
        self.sender_id = sender_id
        self.chat_id = chat_id
        self.id = message_id
        self.raw_text = text
        self.is_private = kw.get("is_private", True)
        self.out = kw.get("out", False)
        self.date = kw.get("date", datetime.now(UTC))
        self.sender = SimpleNamespace(bot=kw.get("bot", False))
        self.replies = []

    async def get_sender(self):
        return self.sender

    async def reply(self, text):
        self.replies.append(text)


class Generator:
    def __init__(self):
        self.calls = []

    async def generate(self, message):
        self.calls.append(message)
        await asyncio.sleep(0.01)
        return "Hello back"


def test_config_fails_closed_without_opt_in(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "123")
    monkeypatch.setenv("TG_API_HASH", "placeholder")
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("LLM_MODEL", "dummy")
    monkeypatch.delenv("DM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("DM_SEND_ENABLED", raising=False)
    config = Config.from_env()
    assert config.allowed_user_ids == frozenset()
    assert not config.send_enabled


def test_config_explicit_allow_all_enables_send_without_ids(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "123")
    monkeypatch.setenv("TG_API_HASH", "placeholder")
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("LLM_MODEL", "dummy")
    monkeypatch.setenv("DM_ALLOWED_USER_IDS", "")
    monkeypatch.setenv("DM_ALLOW_ALL", "true")
    monkeypatch.setenv("DM_SEND_ENABLED", "true")
    config = Config.from_env()
    assert config.allow_all
    assert config.send_enabled


def test_config_rejects_send_without_allowlist(monkeypatch):
    monkeypatch.setenv("DM_ALLOW_ALL", "false")
    monkeypatch.setenv("TG_API_ID", "123")
    monkeypatch.setenv("TG_API_HASH", "placeholder")
    monkeypatch.setenv("DM_ALLOWED_USER_IDS", "")
    monkeypatch.setenv("DM_SEND_ENABLED", "true")
    with pytest.raises(ValueError, match="allowlist"):
        Config.from_env()


@pytest.mark.parametrize("changes", [
    {"out": True}, {"is_private": False}, {"bot": True},
    {"sender_id": 1, "chat_id": 1}, {"sender_id": 99, "chat_id": 99},
    {"sender_id": 42, "chat_id": -42}, {"text": "  "},
    {"date": datetime.now(UTC) - timedelta(days=1)},
])
@pytest.mark.asyncio
async def test_unsafe_events_never_generate_or_reply(tmp_path, changes):
    generator = Generator()
    with DraftStore(tmp_path / "drafts.sqlite3") as store:
        assistant = DMAssistant(1, frozenset({42}), False, generator, store)
        event = Event(**changes)
        await assistant.handle(event)
        assert not generator.calls
        assert not event.replies
        assert store.drafts() == []


@pytest.mark.asyncio
async def test_explicit_allow_all_replies_to_human_dms_only(tmp_path):
    generator = Generator()
    with DraftStore(tmp_path / "drafts.sqlite3") as store:
        assistant = DMAssistant(1, frozenset(), True, generator, store, allow_all=True)
        human = Event(sender_id=99, chat_id=99)
        bot = Event(sender_id=88, chat_id=88, bot=True)
        group = Event(sender_id=77, chat_id=-77, is_private=False)
        for event in (human, bot, group):
            await assistant.handle(event)
        assert human.replies == ["Hello back"]
        assert bot.replies == group.replies == []
        assert generator.calls == ["hello"]


@pytest.mark.asyncio
async def test_draft_default_deduplicates_even_under_concurrency(tmp_path):
    generator = Generator()
    with DraftStore(tmp_path / "drafts.sqlite3") as store:
        assistant = DMAssistant(1, frozenset({42}), False, generator, store)
        event = Event()
        await asyncio.gather(*(assistant.handle(event) for _ in range(5)))
        assert generator.calls == ["hello"]
        assert store.drafts() == [(42, 7, "Hello back")]
        assert event.replies == []
        assert store.path.stat().st_mode & 0o777 == 0o600
        # A new assistant instance sharing the persisted store still must not process it.
        await DMAssistant(1, frozenset({42}), True, generator, store).handle(event)
        assert event.replies == []


@pytest.mark.asyncio
async def test_explicit_send_replies_only_once_to_allowlisted_user(tmp_path):
    generator = Generator()
    with DraftStore(tmp_path / "drafts.sqlite3") as store:
        assistant = DMAssistant(1, frozenset({42}), True, generator, store)
        event = Event()
        await assistant.handle(event)
        await assistant.handle(event)
        assert event.replies == ["Hello back"]
        assert store.drafts() == []


def test_llm_instruction_identifies_personal_assistant_without_impersonating_owner(monkeypatch):
    from telegram_dm_assistant import llm

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, *_args):
            return json.dumps({"choices": [{"message": {"content": "Salom!"}}]}).encode()

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data))
        return Response()

    monkeypatch.setattr(llm, "urlopen", fake_urlopen)
    answer = llm.LLMClient("https://example.com/v1", "test-key", "test-model")._request("Salom")
    instruction = captured["messages"][0]["content"].lower()
    assert answer == "Salom!"
    assert "personal assistant" in instruction
    assert "not the owner" in instruction
    assert "same language" in instruction
    assert "do not claim" in instruction
    assert captured["messages"][1]["content"] == "Salom"


def test_trim_reply_respects_telegram_utf16_and_does_not_send_empty():
    assert trim_reply("  hey  ") == "hey"
    assert len(trim_reply("😀" * 3000).encode("utf-16-le")) <= 7000
    assert trim_reply(" ") == ""
