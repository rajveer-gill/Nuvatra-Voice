"""Voice session persistence and Redis fail-closed behavior."""

import pytest

from voice.call_sid import SAMPLE_CALL_SID
from voice.call_session_store import MemoryCallSessionStore, reset_call_session_store_for_tests


def test_persist_call_session_skips_after_cleanup(monkeypatch):
    import main as m
    from unittest.mock import MagicMock

    store = MagicMock()
    store.exists.return_value = False
    monkeypatch.setattr(m, "call_store", store)
    m._persist_call_session(SAMPLE_CALL_SID, {"client_id": "ghost"})
    store.save.assert_not_called()
    store.exists.assert_called_once()


def test_merge_call_session_persists_outcome():
    import main as m

    reset_call_session_store_for_tests(MemoryCallSessionStore())
    sid = SAMPLE_CALL_SID
    m.call_store.create(sid, {"client_id": "t1"})
    m._merge_call_session(sid, {"outcome": "forwarded"})
    assert m.call_store.get(sid)["outcome"] == "forwarded"


def test_validate_booking_anyone_without_staff_field(monkeypatch):
    import main as m

    monkeypatch.setattr(
        m,
        "get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}],
            "services": [{"id": "svc1", "name": "Haircut", "price": 20, "duration_minutes": 30}],
        },
    )
    ok, msg, staff_id, service = m._validate_booking_requirements(
        {"reason": "Haircut", "name": "Sam", "date": "2026-06-02", "time": "14:00"},
        conversation_history=[
            {"role": "user", "content": "haircut tomorrow at 2pm, anyone is fine"}
        ],
    )
    assert ok
    assert staff_id is None
    assert service == "Haircut"
    assert msg is None


def test_redis_url_without_memory_backend_raises(monkeypatch):
    from voice import call_session_store as cs

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:59999/0")
    monkeypatch.delenv("VOICE_STATE_BACKEND", raising=False)
    cs.reset_call_session_store_for_tests(None)
    cs._store = None  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="Redis call session store unavailable"):
        cs.get_call_session_store()
