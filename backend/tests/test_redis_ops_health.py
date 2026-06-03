"""Redis ops health helper tests (no credential leakage)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from voice import redis_ops_health as roh
from voice.call_session_store import MemoryCallSessionStore, reset_call_session_store_for_tests


@pytest.fixture(autouse=True)
def _memory_store():
    reset_call_session_store_for_tests(MemoryCallSessionStore())
    yield


def test_redis_url_scheme_ok():
    assert roh.redis_url_scheme_ok("redis://127.0.0.1:6379/0")
    assert roh.redis_url_scheme_ok("rediss://:secret@10.0.0.5:6379")
    assert not roh.redis_url_scheme_ok("http://example.com")


def test_redis_host_looks_external_localhost_false():
    assert roh.redis_host_looks_external("redis://127.0.0.1:6379/0") is False
    assert roh.redis_host_looks_external("redis://localhost:6379/0") is False
    assert roh.redis_host_looks_external("redis://red-abc.render.com:6379") is False


def test_redis_host_looks_external_public_ip_true():
    assert roh.redis_host_looks_external("redis://8.8.8.8:6379/0") is True
    assert roh.redis_host_looks_external("redis://0.0.0.0:6379/0") is True


def test_redis_ops_health_never_leaks_password(monkeypatch):
    secret = "super-secret-redis-password-xyz"
    monkeypatch.setenv("REDIS_URL", f"redis://:{secret}@127.0.0.1:6379/0")
    with patch.object(roh, "_ping_redis", return_value=True):
        with patch.object(roh, "_voice_state_backend_name", return_value="redis"):
            payload = roh.redis_ops_health()
    blob = json.dumps(payload)
    assert secret not in blob
    assert payload["redis_url_scheme_ok"] is True


def test_redis_ops_health_ping_failure_not_production_ready(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    with patch.object(roh, "_ping_redis", return_value=False):
        with patch.object(roh, "_voice_state_backend_name", return_value="redis"):
            payload = roh.redis_ops_health()
    assert payload["redis_ping_ok"] is False
    assert payload["redis_production_ready"] is False


def test_redis_ops_health_url_set_memory_backend_inconsistent(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    with patch.object(roh, "_ping_redis", return_value=True):
        with patch.object(roh, "_voice_state_backend_name", return_value="memory"):
            payload = roh.redis_ops_health()
    assert payload["redis_config_consistent"] is False
    assert payload["redis_production_ready"] is False


def test_redis_ops_health_production_ready_when_all_ok(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    with patch.object(roh, "_ping_redis", return_value=True):
        with patch.object(roh, "_voice_state_backend_name", return_value="redis"):
            payload = roh.redis_ops_health()
    assert payload["redis_production_ready"] is True


def test_create_redis_client_rediss_uses_ssl(monkeypatch):
    import sys
    from unittest.mock import MagicMock

    from voice.call_session_store import create_redis_client

    fake_redis = MagicMock()
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    create_redis_client("rediss://127.0.0.1:6379/0")
    _, kwargs = fake_redis.from_url.call_args
    assert kwargs.get("ssl_cert_reqs") == "required"
