"""Conversation-history lost-update fix: the GPT background task must not clobber a
caller turn that arrived while it was generating (the bug that made the AI re-ask for
info already given under concurrent-call load)."""

import asyncio
from unittest.mock import MagicMock

import voice_service
from voice.call_session_store import MemoryCallSessionStore


def test_merge_history_preserves_concurrent_caller_turn():
    # Latest stored history gained a caller turn (user_2) after the GPT task snapshotted.
    latest = {"conversation_history": [
        {"role": "user", "content": "user_1"},
        {"role": "user", "content": "user_2"},  # arrived while GPT was generating
    ]}
    # The task's snapshot only had user_1, plus the assistant reply it just produced.
    snapshot = {"conversation_history": [
        {"role": "user", "content": "user_1"},
        {"role": "assistant", "content": "assistant_1"},
    ]}
    voice_service._merge_history_into(latest, snapshot)
    contents = [m["content"] for m in snapshot["conversation_history"]]
    # user_2 must survive, and the assistant reply is appended — nothing lost.
    assert "user_1" in contents
    assert "user_2" in contents
    assert "assistant_1" in contents
    assert contents.count("user_1") == 1  # no duplicates


def test_merge_history_no_dupe_when_already_present():
    latest = {"conversation_history": [{"role": "user", "content": "a"}]}
    snapshot = {"conversation_history": [{"role": "user", "content": "a"}]}
    voice_service._merge_history_into(latest, snapshot)
    assert snapshot["conversation_history"] == [{"role": "user", "content": "a"}]


def test_persist_generated_session_locked_noop_for_memory_store(monkeypatch):
    # In-memory store: call_data is the live object, so the locked merge is a no-op
    # (and must not touch the store).
    store = MemoryCallSessionStore()
    monkeypatch.setattr(runtime_call_store_target(), "call_store", store, raising=False)
    called = {"save": False}
    monkeypatch.setattr(store, "save", lambda *a, **k: called.__setitem__("save", True))
    asyncio.run(
        voice_service.persist_generated_session_locked("CA" + "0" * 32, {"conversation_history": []})
    )
    assert called["save"] is False


def runtime_call_store_target():
    import runtime
    return runtime
