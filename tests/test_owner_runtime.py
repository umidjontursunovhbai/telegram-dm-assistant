import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from test_assistant import Event
from test_history import Client

from telegram_dm_assistant import llm, main
from telegram_dm_assistant.assistant import DMAssistant, DraftStore
from telegram_dm_assistant.config import Config


@pytest.mark.parametrize("reply_as_owner", [True, False])
async def test_runtime_wires_owner_flag_into_model_without_network(tmp_path, monkeypatch, reply_as_owner):
    handlers = []

    class Client:
        async def start(self):
            pass

        async def get_me(self):
            return SimpleNamespace(id=1)

        def add_event_handler(self, handler, event_filter):
            handlers.append(handler)

        async def run_until_disconnected(self):
            assert handlers[0].__self__.generator.reply_as_owner is reply_as_owner
            assert handlers[0].__self__.context_enabled
            assert handlers[0].__self__.excluded_ids == frozenset({99})

        async def disconnect(self):
            pass

    monkeypatch.setattr(main, "TelegramClient", lambda *_a, **_kw: Client())
    config = Config(123, "dummy", frozenset({42}), False, "openrouter", "dummy", "dummy",
                    "https://example.com", tmp_path / "data", excluded_user_ids=frozenset({99}),
                    context_enabled=True, reply_as_owner=reply_as_owner)
    await main.run(config)
    assert len(handlers) == 2


@pytest.mark.parametrize("send_enabled", [True, False])
async def test_owner_identity_failure_produces_no_reply_or_draft_and_no_retry(
    tmp_path, monkeypatch, send_enabled,
):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "I'm ChatGPT."}}]},
    ).encode()
    provider = MagicMock(return_value=response)
    monkeypatch.setattr(llm, "urlopen", provider)
    generator = llm.LLMClient("https://example.com", "dummy", "dummy", reply_as_owner=True)
    with DraftStore(tmp_path / "db") as store:
        assistant = DMAssistant(1, {42}, send_enabled, generator, store,
                                context_enabled=True, client=Client())
        event = Event()
        with pytest.raises(ValueError, match="Unsafe owner-mode self-identification"):
            await assistant.handle(event)
        await assistant.handle(event)
        assert provider.call_count == 1
        assert event.replies == []
        assert store.drafts() == []
        assert not any(row["kind"] == "assistant" for row in store.messages(1, 42))


async def test_owner_voice_sent_output_remains_assistant_not_style_evidence(tmp_path, monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "ha aka"}}]},
    ).encode()
    monkeypatch.setattr(llm, "urlopen", lambda *_a, **_kw: response)
    generator = llm.LLMClient("https://example.com", "dummy", "dummy", reply_as_owner=True)
    with DraftStore(tmp_path / "db") as store:
        assistant = DMAssistant(1, {42}, True, generator, store,
                                context_enabled=True, client=Client())
        event = Event()

        async def fake_reply(text):
            assert text == "ha aka"
            return SimpleNamespace(id=8, date=datetime.now(UTC))

        event.reply = fake_reply
        await assistant.handle(event)
        await assistant.handle_outgoing(Event(sender_id=1, message_id=8, out=True, text="ha aka"))
        rows = store.context(1, 42, "", before_id=9)
        assert next(row for row in rows if row["id"] == 8)["kind"] == "assistant"
        assert [row["id"] for row in rows if row["kind"] == "owner"] == [2]
