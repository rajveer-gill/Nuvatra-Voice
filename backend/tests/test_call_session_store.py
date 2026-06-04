"""Call session store unit tests."""
import pytest

from voice.call_sid import SAMPLE_CALL_SID
from voice.call_session_store import (
    MemoryCallSessionStore,
    RedisCallSessionStore,
    UtteranceLockError,
    _ResponseStatusProxy,
    reset_call_session_store_for_tests,
)

SID_A = SAMPLE_CALL_SID
SID_B = "CAbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
SID_REDIS = "CAcccccccccccccccccccccccccccccccc"


@pytest.fixture(autouse=True)
def _fresh_memory_store():
    reset_call_session_store_for_tests(MemoryCallSessionStore())
    yield


def test_memory_create_get_delete():
    store = MemoryCallSessionStore()
    store.create(SID_A, {"client_id": "t1", "conversation_history": []})
    assert store.exists(SID_A)
    data = store.get(SID_A)
    assert data["client_id"] == "t1"
    store.cleanup_call(SID_A)
    assert not store.exists(SID_A)


def test_memory_rejects_invalid_call_sid():
    store = MemoryCallSessionStore()
    with pytest.raises(ValueError, match="invalid call_sid"):
        store.create("CA1", {"client_id": "t1"})
    assert not store.exists("CA1")


def test_memory_response_status_pop():
    store = MemoryCallSessionStore()
    store.set_response_status(SID_A, {"status": "pending"})
    assert store.get_response_status(SID_A)["status"] == "pending"
    popped = store.pop_response_status(SID_A)
    assert popped["status"] == "pending"
    assert store.get_response_status(SID_A) is None


def test_memory_incr_media_stream_gen():
    store = MemoryCallSessionStore()
    store.create(SID_A, {"media_stream_gen": 0})
    assert store.incr_media_stream_gen(SID_A) == 1
    assert store.get(SID_A)["media_stream_gen"] == 1
    assert store.get_media_stream_max_gen(SID_A) == 1


def test_merge_session_persists_fields():
    store = MemoryCallSessionStore()
    store.create(SID_A, {"client_id": "t1"})
    assert store.merge_session(SID_A, {"twilio_public_base_url": "https://api.example.com"})
    row = store.get(SID_A) or {}
    assert row.get("twilio_public_base_url") == "https://api.example.com"
    store.incr_media_stream_gen(SID_A)
    row2 = store.get(SID_A) or {}
    assert row2.get("twilio_public_base_url") == "https://api.example.com"
    assert row2.get("media_stream_gen") == 1


def test_memory_incr_rejects_non_string_call_sid():
    store = MemoryCallSessionStore()
    store.create(SID_A, {})
    assert store.incr_media_stream_gen("not-a-valid-sid") == 0
    assert store.incr_media_stream_gen({"bad": "dict"}) == 0  # type: ignore[arg-type]


def test_memory_proxy_dict_compat():
    store = MemoryCallSessionStore()
    store.sessions[SID_B] = {"client_id": "x"}
    store.response_status[SID_B] = {"status": "ready"}
    assert SID_B in store.sessions
    assert store.response_status[SID_B]["status"] == "ready"
    store.cleanup_call(SID_B)
    assert SID_B not in store.sessions


def test_redis_response_status_proxy_delitem():
    """Redis response_status proxy must support del (respond_with_audio cleanup)."""
    inner = MemoryCallSessionStore()

    class _Wrap:
        def __init__(self, mem: MemoryCallSessionStore):
            self._mem = mem

        def get_response_status(self, call_sid: str):
            return self._mem.get_response_status(call_sid)

        def set_response_status(self, call_sid: str, status: dict):
            self._mem.set_response_status(call_sid, status)

        def pop_response_status(self, call_sid: str):
            return self._mem.pop_response_status(call_sid)

    proxy = _ResponseStatusProxy(_Wrap(inner))  # type: ignore[arg-type]
    inner.set_response_status(SID_A, {"status": "ready"})
    assert SID_A in proxy
    del proxy[SID_A]
    assert SID_A not in proxy
    with pytest.raises(KeyError):
        del proxy[SID_A]


def test_redis_sessions_proxy_delitem():
    """Sessions proxy must support del for cleanup paths."""
    inner = MemoryCallSessionStore()
    inner.create(SID_A, {"client_id": "t1"})

    class _Wrap:
        def __init__(self, mem: MemoryCallSessionStore):
            self._mem = mem

        def exists(self, call_sid: str) -> bool:
            return self._mem.exists(call_sid)

        def get(self, call_sid: str):
            return self._mem.get(call_sid)

        def save(self, call_sid: str, data: dict) -> None:
            self._mem.save(call_sid, data)

        def create(self, call_sid: str, data: dict) -> None:
            self._mem.create(call_sid, data)

        def delete(self, call_sid: str) -> None:
            self._mem.delete(call_sid)

        def merge_session(self, call_sid: str, updates: dict) -> bool:
            return self._mem.merge_session(call_sid, updates)

        def list_call_sids(self) -> list[str]:
            return self._mem.list_call_sids()

    from voice.call_session_store import _SessionsProxy

    proxy = _SessionsProxy(_Wrap(inner))  # type: ignore[arg-type]
    assert SID_A in proxy
    del proxy[SID_A]
    assert SID_A not in proxy


@pytest.mark.asyncio
async def test_memory_utterance_lock_invalid_sid_raises():
    store = MemoryCallSessionStore()
    with pytest.raises(UtteranceLockError):
        async with store.utterance_lock("bad"):
            pass


@pytest.mark.skipif(not __import__("os").getenv("REDIS_URL"), reason="REDIS_URL not set")
def test_redis_roundtrip():
    import os

    store = RedisCallSessionStore(os.environ["REDIS_URL"])
    sid = SID_REDIS
    store.cleanup_call(sid)
    store.create(sid, {"client_id": "redis-test", "conversation_history": [{"role": "user", "content": "hi"}]})
    assert store.exists(sid)
    store.set_response_status(sid, {"status": "pending"})
    assert store.get_response_status(sid)["status"] == "pending"
    store.save(sid, {**store.get(sid), "booking_intent": True})
    assert store.get(sid).get("booking_intent") is True
    store.cleanup_call(sid)
    assert not store.exists(sid)
