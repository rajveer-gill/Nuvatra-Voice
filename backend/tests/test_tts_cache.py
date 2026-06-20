"""Disk + memory cache for greeting and got-it voice clips."""

from pathlib import Path

from voice.tts_cache import get_cached, invalidate_client, put_cached


def test_tts_cache_disk_roundtrip(tmp_path):
    key = ("tenant-a", "Hello there", "fable", 1.0)
    data = b"fake-mp3-bytes"
    put_cached(tmp_path, "greeting", key, data)
    assert get_cached(tmp_path, "greeting", key) == data

    invalidate_client(tmp_path, "tenant-a")
    assert get_cached(tmp_path, "greeting", key) is None


def test_tts_cache_memory_hit_before_disk(tmp_path):
    key = ("tenant-b", "Got it", "onyx", 1.1)
    put_cached(tmp_path, "got_it", key, b"abc")
    path = tmp_path / "clients" / "tenant-b" / "voice_cache"
    for p in path.glob("*.mp3"):
        p.unlink()
    assert get_cached(tmp_path, "got_it", key) == b"abc"


def test_tts_cache_filler_kind_roundtrip(tmp_path):
    # The progressive-filler endpoint caches under "filler"; it was missing from the
    # registry and raised KeyError on every call (caller heard silence).
    key = ("tenant-c", "Almost there.", "fable", 1.0)
    assert get_cached(tmp_path, "filler", key) is None  # miss, not KeyError
    put_cached(tmp_path, "filler", key, b"xyz")
    assert get_cached(tmp_path, "filler", key) == b"xyz"


def test_tts_cache_unknown_kind_degrades_to_miss(tmp_path):
    # Defensive: a not-yet-registered kind must miss, never KeyError mid-call.
    assert get_cached(tmp_path, "not_a_real_kind", ("t", "x")) is None
    put_cached(tmp_path, "not_a_real_kind", ("t", "x"), b"q")
    assert get_cached(tmp_path, "not_a_real_kind", ("t", "x")) == b"q"
