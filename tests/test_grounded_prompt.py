import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from telegram_dm_assistant import llm
from telegram_dm_assistant.assistant import DraftStore


@pytest.mark.parametrize("subject,continuation,pointer", [
    ("Umidjon qani", "Biliber", None),
    ("Where is the parcel?", "Find out", 20),
    ("Where is the parcel?", "Check it", 999),
])
async def test_prompt_maps_subject_reply_target_and_dedicated_actual_owner_voice(
    tmp_path, monkeypatch, subject, continuation, pointer,
):
    captured = {}
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "offline fixture output"}}]},
    ).encode()

    def request(req, timeout):
        captured.update(json.loads(req.data))
        return response

    monkeypatch.setattr(llm, "urlopen", request)
    date = datetime(2020, 1, 1, tzinfo=UTC)
    with DraftStore(tmp_path / "db") as store:
        for mid in range(1, 81):
            kind = "owner" if mid in (20, 21, 22) else "assistant"
            text = {20: "Ha chunarli", 21: "Assalomalekum", 22: "Yeah no problem brotha",
                    79: subject, 80: "current location unknown"}.get(mid, "robotic assistant clutter")
            store.record(1, 42, mid, date, "incoming" if mid == 79 else kind, text)
        context = store.context(1, 42, continuation, before_id=81, reply_to_id=pointer)
        assert await llm.LLMClient("https://example.invalid", "dummy", "dummy", True).generate(
            continuation, context=context,
        ) == "offline fixture output"
    messages = captured["messages"]
    system = messages[0]["content"].lower()
    for rule in ("active conversational subject", "direct reply target", "short colloquial",
                 "preceding exchange", "do not ask what", "older factual subject",
                 "current update", "do not repeat", "dedicated owner style", "not style evidence"):
        assert rule in system
    assert "current location" in system and "automation" in system
    styles = [m for m in messages if m["content"].startswith("Dedicated owner style examples:")]
    assert len(styles) == 1
    examples = json.loads(styles[0]["content"].split(":", 1)[1])
    assert [r["text"] for r in examples] == [
        "Ha chunarli", "Assalomalekum", "Yeah no problem brotha"]
    assert all(r["kind"] == "owner" for r in examples)
    assert len(examples) <= 8
    assert styles[0] == messages[1]
    facts = [json.loads(m["content"].split(":", 1)[1]) for m in messages
             if m["content"].startswith("Untrusted historical")]
    assert [r["id"] for r in facts] == sorted(r["id"] for r in facts)
    assert next(r for r in facts if r["id"] == 79)["text"] == subject
    assert next(r for r in facts if r["id"] == 80)["recent_exchange"]
    targets = [r["id"] for r in facts if r.get("direct_reply_target")]
    assert targets == ([20] if pointer == 20 else [])
    if pointer == 999:
        assert any("reply target unavailable" in m["content"].lower() for m in messages)
    assert sum(len(r["text"]) for r in facts + examples) <= 16000
    assert messages[-1] == {"role": "user", "content": continuation}


@pytest.mark.parametrize("subject,detail,query", [
    ("Belissimoda clicklar qoshilgan ekanku bro", "Iphonedayam", "Belissimo nkma boldi"),
    ("Atlas payments supported now", "On tablets too", "What happened with Atlas?"),
])
async def test_explicit_subject_switch_uses_old_neighbor_evidence_not_unrelated_recent_topic(
    tmp_path, monkeypatch, subject, detail, query,
):
    captured = {}
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "offline output"}}]},
    ).encode()

    def request(req, timeout):
        captured.update(json.loads(req.data))
        return response

    monkeypatch.setattr(llm, "urlopen", request)
    with DraftStore(tmp_path / "db") as store:
        date = datetime(2020, 1, 1, tzinfo=UTC)
        for mid in range(1, 81):
            text = {20: subject, 21: detail}.get(mid, "different recent topic")
            kind = "owner" if mid in (20, 21) or 32 <= mid < 40 else "incoming"
            store.record(1, 42, mid, date, kind, text)
        await llm.LLMClient("https://example.invalid", "dummy", "dummy", True).generate(
            query, context=store.context(1, 42, query, before_id=81),
        )
    system = captured["messages"][0]["content"].lower()
    assert "explicit topic switch" in system
    assert "unrelated recent topic" in system
    assert "media placeholders" in system
    facts = [json.loads(m["content"].split(":", 1)[1]) for m in captured["messages"]
             if m["content"].startswith("Untrusted historical")]
    assert next(r for r in facts if r["id"] == 20)["text"] == subject
    assert next(r for r in facts if r["id"] == 21)["text"] == detail
    assert next(r for r in facts if r["id"] == 21)["relevant_neighbor"]
