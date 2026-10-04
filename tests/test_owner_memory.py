from datetime import UTC, datetime

import pytest

from telegram_dm_assistant.assistant import DraftStore


@pytest.mark.parametrize("budget", [400, 16000, 32000])
def test_owner_examples_survive_assistant_dominated_recent_history_with_hard_budget(tmp_path, budget):
    date = datetime(2020, 1, 1, tzinfo=UTC)
    with DraftStore(tmp_path / "db") as store:
        for mid in range(1, 101):
            kind = "owner" if 20 <= mid < 40 else "assistant"
            text = f"my own style {mid} " if kind == "owner" else "assistant template "
            if mid == 8:
                text = "Orion deadline Friday "
            store.record(1, 42, mid, date, kind, text * 1000)
        for owner, chat, mid in [(2, 42, 39), (1, 99, 39), (1, 42, 101)]:
            store.record(owner, chat, mid, date, "owner", "private foreign or future secret")
        context = store.context(1, 42, "Orion", before_id=101, budget=budget)
        samples = [row for row in context if row["kind"] == "owner"]
        assert len(samples) == 8
        assert [row["id"] for row in samples] == list(range(32, 40))
        assert all("my own style" in row["text"] for row in samples)
        assert sum(len(row["text"]) for row in context) <= min(budget, 16000)
        assert any("Friday" in row["text"] for row in context)
        assert context[-1]["id"] == 100
        assert not any("secret" in row["text"] for row in context)
        assert len({row["id"] for row in context}) == len(context)
