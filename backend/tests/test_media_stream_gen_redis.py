"""Redis media stream generation persistence (atomic mgen key)."""

import pytest

from voice.call_sid import SAMPLE_CALL_SID
from voice.call_session_store import RedisCallSessionStore

SID = SAMPLE_CALL_SID


@pytest.mark.skipif(not __import__("os").getenv("REDIS_URL"), reason="REDIS_URL not set")
def test_redis_incr_media_stream_gen_atomic_and_persisted():
    import os

    store = RedisCallSessionStore(os.environ["REDIS_URL"])
    store.cleanup_call(SID)
    store.create(SID, {"client_id": "t1", "conversation_history": []})
    g1 = store.incr_media_stream_gen(SID)
    g2 = store.incr_media_stream_gen(SID)
    assert g1 == 1
    assert g2 == 2
    assert store.get_media_stream_max_gen(SID) == 2
    assert int(store.get(SID)["media_stream_gen"]) == 2
    store.cleanup_call(SID)
    assert store.get_media_stream_max_gen(SID) == 0
