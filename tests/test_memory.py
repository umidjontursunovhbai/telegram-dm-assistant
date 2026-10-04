from datetime import UTC, datetime

from telegram_dm_assistant.assistant import DraftStore


def test_history_database_allows_readers_without_per_message_fsync(tmp_path):
    with DraftStore(tmp_path / "memory.sqlite3") as store:
        assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store.db.execute("PRAGMA synchronous").fetchone()[0] == 1


def test_history_retains_chronology_deduplication_and_owner_chat_isolation(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with DraftStore(path) as store:
        assert hasattr(store, "record"), "persistent history storage is missing"
        for owner, chat, mid, text in [(1, 42, 3, "later"), (1, 42, 1, "first"),
                                       (2, 42, 1, "other owner"), (1, 99, 1, "other chat")]:
            store.record(owner, chat, mid, datetime.now(UTC), "incoming", text)
        store.record(1, 42, 3, datetime.now(UTC), "incoming", "later")
        assert [row["text"] for row in store.messages(1, 42)] == ["first", "later"]
        store.set_checkpoint(1, 42, 3, complete=True)
    with DraftStore(path) as store:
        assert len(store.messages(1, 42)) == 2
        assert store.checkpoint(1, 42) == (3, True)
        assert [row["text"] for row in store.messages(2, 42)] == ["other owner"]
        assert [row["text"] for row in store.messages(1, 99)] == ["other chat"]


def test_context_recalls_old_keywords_recent_and_baseline_with_a_hard_budget(tmp_path):
    with DraftStore(tmp_path / "memory.sqlite3") as store:
        assert hasattr(store, "context"), "bounded historical retrieval missing"
        date = datetime(2020, 1, 1, tzinfo=UTC)
        for mid in range(1, 101):
            text = "salom aka" if mid == 1 else "unrelated filler " * 100
            if mid == 8:
                text = "Project Orion deadline is Friday"
            store.record(1, 42, mid, date, "owner" if mid % 2 == 0 else "incoming", text)
        store.record(2, 42, 8, date, "incoming", "Orion other-account secret")
        store.record(1, 99, 8, date, "incoming", "Orion other-chat secret")
        context = store.context(1, 42, "what was the Orion deadline?", before_id=101)
        assert context[0]["id"] == 1
        assert any("Friday" in turn["text"] for turn in context)
        assert context[-1]["id"] == 100
        assert not any("secret" in turn["text"] for turn in context)
        assert sum(len(turn["text"]) for turn in context) <= 16000
        assert [t["id"] for t in context] == sorted(t["id"] for t in context)


def test_unicode_keyword_matching_ranks_multiple_terms_above_common_words(tmp_path):
    with DraftStore(tmp_path / "db") as store:
        date = datetime.now(UTC)
        for mid in range(1, 101):
            text = "проект общий" if mid > 8 else "filler"
            if mid == 8:
                text = "ПРОЕКТ ОРИОН срок пятница"
            store.record(1, 42, mid, date, "incoming", text)
        context = store.context(1, 42, "проект орион", before_id=101)
        assert any("пятница" in row["text"] for row in context)
