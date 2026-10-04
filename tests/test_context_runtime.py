from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_assistant import Event, Generator
from test_history import Client

from telegram_dm_assistant.assistant import DMAssistant, DraftStore
from telegram_dm_assistant.history import HistoryImporter


@pytest.mark.asyncio
async def test_enabled_imports_before_reply_and_records_actual_sent_id(tmp_path):
    import inspect
    assert "context_enabled" in inspect.signature(DMAssistant).parameters
    client = Client()
    class Model:
        async def generate(self, text, context):
            assert [row["id"] for row in context] == [1, 2, 3]
            assert store.messages(1, 42)[-1]["id"] == 7
            return "reply"
    with DraftStore(tmp_path / "db") as store:
        assistant = DMAssistant(1, {42}, True, Model(), store,
                                context_enabled=True, client=client)
        event = Event()
        async def reply(text):
            return SimpleNamespace(id=8, date=datetime.now(UTC), raw_text=text)
        event.reply = reply
        await assistant.handle(event)
        assert [(r["id"], r["kind"]) for r in store.messages(1, 42)][-2:] == [
            (7, "incoming"), (8, "assistant")]
        manual = Event(sender_id=1, message_id=9, out=True, text="manual")
        await assistant.handle_outgoing(manual)
        assert store.messages(1, 42)[-1]["kind"] == "owner"
        # A duplicated outgoing update must not relabel an assistant message.
        manual.id = 8
        await assistant.handle_outgoing(manual)
        assert store.messages(1, 42)[-2]["kind"] == "assistant"


@pytest.mark.asyncio
async def test_disabled_keeps_old_behavior_without_history(tmp_path):
    with DraftStore(tmp_path / "db") as store:
        generator = Generator()
        assistant = DMAssistant(1, {42}, False, generator, store)
        await assistant.handle(Event())
        assert generator.calls == ["hello"]
        assert store.messages(1, 42) == []


@pytest.mark.asyncio
async def test_enabled_outgoing_rejects_bots_deleted_excluded_and_groups(tmp_path):
    client = Client()
    from telethon.tl.types import User
    async def resolve(peer):
        return User(id=peer, bot=peer == 88, deleted=peer == 99)
    client.get_entity = resolve
    with DraftStore(tmp_path / "db") as store:
        assistant = DMAssistant(1, set(), False, Generator(), store, allow_all=True,
                                excluded_ids={55}, context_enabled=True, client=client)
        for peer in (88, 99, 55, 1, -42):
            await assistant.handle_outgoing(Event(sender_id=1, chat_id=peer, out=True))
            assert store.messages(1, peer) == []


@pytest.mark.asyncio
async def test_context_records_media_without_reply_and_never_replays_backlog(tmp_path):
    from datetime import timedelta
    with DraftStore(tmp_path / "db") as store:
        generator = Generator()
        client = Client()
        assistant = DMAssistant(1, {42}, False, generator, store,
                                context_enabled=True, client=client)
        await assistant.handle(Event(date=datetime.now(UTC) - timedelta(days=1)))
        assert client.calls == []
        await assistant.handle(Event(text=""))
        assert store.messages(1, 42)[-1]["text"] == "[unsupported media or service message]"
        assert not generator.calls
        assert store.drafts() == []


@pytest.mark.asyncio
async def test_runtime_import_failure_does_not_reserve_and_can_resume(tmp_path):
    class Model:
        async def generate(self, text, context):
            assert len(context) == 3
            return "draft"
    client = Client()
    client.fail = True
    with DraftStore(tmp_path / "db") as store:
        assistant = DMAssistant(1, {42}, False, Model(), store,
                                context_enabled=True, client=client)
        event = Event()
        with pytest.raises(RuntimeError, match="interrupted"):
            await assistant.handle(event)
        assert store.db.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0
        assert store.checkpoint(1, 42) == (1, False)
        client.fail = False
        await assistant.handle(event)
        assert store.drafts() == [(42, 7, "draft")]
        assert store.checkpoint(1, 42) == (3, True)


@pytest.mark.parametrize("pointer_source", ["event", "message", "missing"])
async def test_reply_target_reaches_model_and_persists_import_manual_and_assistant(
    tmp_path, pointer_source,
):
    client = Client()
    client.rows[1].reply_to_msg_id = 1
    captured = []

    class Model:
        async def generate(self, text, context):
            captured.append(context)
            return "draft"

    with DraftStore(tmp_path / "db") as store:
        await HistoryImporter(client, store, 1, {42}).ensure(42)
        assert store.messages(1, 42)[1]["reply_to_id"] == 1
        assistant = DMAssistant(1, {42}, True, Model(), store,
                                context_enabled=True, client=client)
        event = Event(text="check it")
        if pointer_source == "event":
            event.reply_to_msg_id = 2
        elif pointer_source == "message":
            event.reply_to_msg_id = None
            event.message = SimpleNamespace(reply_to_msg_id=2)
        else:
            event.reply_to_msg_id = 999
        async def reply(text):
            return SimpleNamespace(id=8, date=datetime.now(UTC))
        event.reply = reply
        await assistant.handle(event)
        targets = [r["id"] for r in captured[0] if r.get("direct_reply_target")]
        assert targets == ([2] if pointer_source != "missing" else [])
        pointer = 2 if pointer_source != "missing" else 999
        assert captured[0].reply_to_id == pointer
        assert store.messages(1, 42)[-2]["reply_to_id"] == pointer
        assert store.messages(1, 42)[-1]["reply_to_id"] == 7
        manual = Event(sender_id=1, message_id=9, out=True, text="owner")
        manual.message = SimpleNamespace(reply_to_msg_id=3)
        await assistant.handle_outgoing(manual)
        assert store.messages(1, 42)[-1]["reply_to_id"] == 3
