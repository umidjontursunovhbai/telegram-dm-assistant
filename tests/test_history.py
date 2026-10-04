from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from telethon.tl.types import User

from telegram_dm_assistant import assistant as module
from telegram_dm_assistant.assistant import DraftStore


class Client:
    def __init__(self):
        self.calls = []
        self.rows = [SimpleNamespace(id=i, date=datetime(2020, 1, i, tzinfo=UTC),
                                     out=i == 2, raw_text=f"text {i}") for i in range(1, 4)]
        self.fail = False

    async def get_entity(self, peer):
        return User(id=peer, bot=peer == 88)

    async def iter_messages(self, peer, **kwargs):
        self.calls.append((peer.id, kwargs))
        for row in self.rows:
            if row.id > kwargs.get("min_id", 0):
                yield row
                if self.fail:
                    raise RuntimeError("interrupted")


@pytest.mark.asyncio
async def test_full_history_is_earliest_first_idempotent_and_resumes_after_restart(tmp_path):
    assert hasattr(module, "HistoryImporter"), "lazy history importer missing"
    client = Client()
    path = tmp_path / "memory.sqlite3"
    with DraftStore(path) as store:
        importer = module.HistoryImporter(client, store, 1, frozenset({42}))
        client.fail = True
        with pytest.raises(RuntimeError, match="interrupted"):
            await importer.ensure(42)
        assert store.checkpoint(1, 42) == (1, False)
    client.fail = False
    with DraftStore(path) as store:
        importer = module.HistoryImporter(client, store, 1, frozenset({42}))
        await importer.ensure(42)
        await importer.ensure(42)
        assert store.checkpoint(1, 42) == (3, True)
        assert [r["id"] for r in store.messages(1, 42)] == [1, 2, 3]
        assert [r["kind"] for r in store.messages(1, 42)] == ["incoming", "owner", "incoming"]
        assert client.calls == [(42, {"reverse": True, "limit": None, "min_id": 0}),
                                (42, {"reverse": True, "limit": None, "min_id": 1})]
        client.rows.append(SimpleNamespace(id=4, date=datetime.now(UTC),
                                           out=True, raw_text="offline owner message"))
        await module.HistoryImporter(client, store, 1, frozenset({42})).ensure(42)
        assert store.messages(1, 42)[-1]["text"] == "offline owner message"


@pytest.mark.asyncio
async def test_excluded_bots_and_non_users_are_not_fetched(tmp_path):
    assert hasattr(module, "HistoryImporter"), "eligibility-gated history importer missing"
    client = Client()
    with DraftStore(tmp_path / "memory.sqlite3") as store:
        importer = module.HistoryImporter(client, store, 1, frozenset(),
                                          allow_all=True, excluded_ids=frozenset({42}))
        async def resolve(peer):
            assert peer not in {42, 1, -4}
            return User(id=88, bot=True) if peer == 88 else SimpleNamespace(id=99)
        client.get_entity = resolve
        for peer in (42, 1, -4, 88, 99):
            assert await importer.ensure(peer) == 0
        assert not client.calls
        assert store.messages(1, 42) == []


@pytest.mark.asyncio
async def test_floodwait_resumes_partial_import_and_bounded_retries(tmp_path):
    from telethon.errors import FloodWaitError
    client = Client()
    sleeps = []
    first = True
    async def rows(peer, **kwargs):
        nonlocal first
        client.calls.append(kwargs)
        for row in client.rows:
            if row.id > kwargs["min_id"]:
                yield row
                if first:
                    first = False
                    raise FloodWaitError(request=None, capture=2)
    async def sleep(seconds):
        sleeps.append(seconds)
    client.iter_messages = rows
    with DraftStore(tmp_path / "db") as store:
        importer = module.HistoryImporter(client, store, 1, {42}, sleep=sleep)
        await importer.ensure(42)
        assert sleeps == [2]
        assert [call["min_id"] for call in client.calls] == [0, 1]
        assert store.checkpoint(1, 42) == (3, True)
        async def flood(peer):
            raise FloodWaitError(request=None, capture=61)
        client.get_entity = flood
        with pytest.raises(FloodWaitError):
            await module.HistoryImporter(client, store, 1, {42}, sleep=sleep).ensure(42)
        assert sleeps == [2]


@pytest.mark.asyncio
async def test_same_chat_concurrent_imports_share_one_full_scan(tmp_path):
    import asyncio
    client = Client()
    with DraftStore(tmp_path / "db") as store:
        importer = module.HistoryImporter(client, store, 1, {42})
        await asyncio.gather(*(importer.ensure(42) for _ in range(10)))
        assert len(client.calls) == 1
        assert len(store.messages(1, 42)) == 3
