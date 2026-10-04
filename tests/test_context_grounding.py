import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from telegram_dm_assistant.assistant import DraftStore


@pytest.mark.parametrize("subject,detail,query", [
    ("Belissimoda clicklar qoshilgan ekanku bro", "Iphonedayam", "Belissimo nkma boldi"),
    ("Orion payment support added", "Android too", "Orion what happened?"),
])
def test_recall_old_subject_includes_adjacent_turns_not_only_keywords(
    tmp_path, subject, detail, query,
):
    date = datetime(2020, 1, 1, tzinfo=UTC)
    with DraftStore(tmp_path / "db") as store:
        for mid in range(1, 81):
            text = {20: "[photo]", 21: subject, 22: detail, 23: "[video]"}.get(mid, "unrelated")
            store.record(1, 42, mid, date + timedelta(seconds=mid),
                         "owner" if mid in (21, 22) or 32 <= mid < 40 else "incoming", text)
        for owner, chat in [(2, 42), (1, 99)]:
            store.record(owner, chat, 22, date, "owner", "foreign secret")
        context = store.context(1, 42, query, before_id=81)
        recalled = {row["id"]: row for row in context}
        # Owner samples alone must not be the reason this neighbor survives.
        assert recalled[22].get("relevant_neighbor") is True
        assert {20, 21, 22, 23} <= recalled.keys()
        assert recalled[22]["text"] == detail
        assert [row["id"] for row in context] == sorted(recalled)
        assert sum(len(row["text"]) for row in context) <= 16000
        assert not any("secret" in row["text"] for row in context)


def test_reply_pointer_additive_migration_preserves_legacy_history(tmp_path):
    path = tmp_path / "db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE messages (owner_id INTEGER, chat_id INTEGER, message_id INTEGER, "
                   "date TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, "
                   "PRIMARY KEY(owner_id, chat_id, message_id))")
        db.execute("INSERT INTO messages VALUES (1, 42, 1, '2020', 'owner', 'legacy')")
    path.chmod(0o600)
    with DraftStore(path) as store:
        assert store.messages(1, 42)[0]["reply_to_id"] is None
        date = datetime(2020, 1, 1, tzinfo=UTC)
        store.record(1, 42, 2, date, "assistant", "reply", reply_to_id=1)
        # Older import/replayed events lacking the pointer must not erase it or relabel output.
        store.record(1, 42, 2, date, "owner", "reply")
    with DraftStore(path) as store:
        rows = {r["id"]: r for r in store.messages(1, 42)}
        assert rows[1]["text"] == "legacy"
        assert rows[2]["reply_to_id"] == 1
        assert rows[2]["kind"] == "assistant"


@pytest.mark.parametrize("reply_to_id", [20, 777, None])
def test_direct_target_prioritized_scoped_bounded_and_missing_is_graceful(tmp_path, reply_to_id):
    date = datetime(2020, 1, 1, tzinfo=UTC)
    with DraftStore(tmp_path / "db") as store:
        for mid in range(1, 101):
            text = "Orion launch details" if mid == 20 else "unrelated " * 1000
            store.record(1, 42, mid, date, "incoming", text)
        store.record(1, 42, 99, date, "assistant", "current status unavailable", reply_to_id=98)
        for owner, chat in [(2, 42), (1, 99)]:
            store.record(owner, chat, 777, date, "owner", "foreign secret")
        for budget in (400, 16000, 32000):
            context = store.context(1, 42, "check it", before_id=801,
                                    reply_to_id=reply_to_id, budget=budget)
            targets = [r for r in context if r.get("direct_reply_target")]
            assert [r["id"] for r in targets] == ([20] if reply_to_id == 20 else [])
            assert context.reply_to_id == reply_to_id
            assert sum(len(r["text"]) for r in context) <= min(budget, 16000)
            assert [r["id"] for r in context] == sorted(r["id"] for r in context)
            assert not any("secret" in r["text"] for r in context)
            assert next(r for r in context if r["id"] == 99)["reply_to_id"] == 98
            assert all(r.get("recent_exchange") for r in context if r["id"] >= 89)
