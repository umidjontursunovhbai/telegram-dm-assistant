from dataclasses import replace
from types import SimpleNamespace

import pytest
from telethon.tl.types import User
from test_history import Client as HistoryClient

from telegram_dm_assistant import main
from telegram_dm_assistant.assistant import DraftStore
from telegram_dm_assistant.config import Config


def config(tmp_path):
    return Config(123, "dummy", frozenset(), True, "openrouter", "dummy", "model",
                  "https://example.com", tmp_path / "data", True, frozenset({55}))


class Client(HistoryClient):
    async def iter_messages(self, peer, **kwargs):
        self.calls.append((peer.id, kwargs))
        for row in self.rows:
            if row.id > kwargs["min_id"]:
                yield row

    async def start(self):
        pass

    async def get_me(self):
        return User(id=1)

    async def disconnect(self):
        self.disconnected = True

    async def iter_dialogs(self):
        for peer in (42, 43, 55, 88):
            yield SimpleNamespace(id=peer, is_user=True, entity=User(id=peer, bot=peer == 88))
        yield SimpleNamespace(id=-3, is_user=False, entity=SimpleNamespace())

    async def get_entity(self, peer):
        if peer == 42 and self.fail:
            raise RuntimeError("secret message must not be printed")
        return await super().get_entity(peer)


def test_cli_backfill_dispatch_and_chat_id_validation(monkeypatch, tmp_path):
    calls = []
    async def backfill(conf, chat_id=None):
        calls.append(chat_id)
        return 1
    monkeypatch.setattr(main.Config, "from_env", lambda: config(tmp_path))
    monkeypatch.setattr(main, "backfill", backfill, raising=False)
    assert main.main(["--backfill", "--chat-id", "42"]) == 1
    assert calls == [42]
    with pytest.raises(SystemExit):
        main.main(["--run", "--chat-id", "42"])
    with pytest.raises(SystemExit):
        main.main(["--backfill", "--chat-id", "-42"])


@pytest.mark.asyncio
async def test_backfill_continues_counts_only_and_is_incremental(tmp_path, monkeypatch, capsys):
    assert hasattr(main, "backfill")
    client = Client()
    client.fail = True
    monkeypatch.setattr(main, "TelegramClient", lambda *a, **kw: client)
    monkeypatch.setattr(main, "LLMClient", lambda *a: pytest.fail("model created"))
    conf = config(tmp_path)
    assert await main.backfill(conf) == 1
    out = capsys.readouterr().out
    assert out.strip() == "Imported chats: 1; skipped: 3; failed: 1; messages: 3"
    assert client.disconnected
    client.fail = False
    assert await main.backfill(conf) == 0
    assert "messages: 3" in capsys.readouterr().out
    assert await main.backfill(conf, 43) == 0
    assert "messages: 0" in capsys.readouterr().out
    with DraftStore(conf.data_dir / "drafts.sqlite3") as store:
        assert len(store.messages(1, 42)) == len(store.messages(1, 43)) == 3
        assert store.messages(1, 55) == store.messages(1, 88) == []
        assert store.drafts() == []


@pytest.mark.asyncio
async def test_enabled_runtime_registers_outgoing_only_when_opted_in(tmp_path, monkeypatch):
    client = Client()
    handlers = []
    client.add_event_handler = lambda handler, builder: handlers.append((handler, builder))
    async def wait():
        pass
    client.run_until_disconnected = wait
    monkeypatch.setattr(main, "TelegramClient", lambda *a, **kw: client)
    await main.run(replace(config(tmp_path), context_enabled=True))
    assert len(handlers) == 2
    assert handlers[0][0].__self__.context_enabled
    assert handlers[1][1].outgoing is True
    assert client.calls == []  # lazy, not a startup replay


@pytest.mark.asyncio
async def test_backfill_disconnect_failure_returns_counts_not_private_exception(tmp_path,
                                                                               monkeypatch,
                                                                               capsys):
    client = Client()
    async def disconnect():
        raise RuntimeError("private secret")
    client.disconnect = disconnect
    monkeypatch.setattr(main, "TelegramClient", lambda *a, **kw: client)
    assert await main.backfill(config(tmp_path), 43) == 1
    assert capsys.readouterr().out.strip() == (
        "Imported chats: 1; skipped: 0; failed: 1; messages: 3")
