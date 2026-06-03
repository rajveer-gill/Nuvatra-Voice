"""Safe Redis ops health checks for admin self-check (no credential leakage)."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from typing import Any, Literal
from urllib.parse import urlparse

from voice.call_session_store import MemoryCallSessionStore, RedisCallSessionStore, create_redis_client, get_call_session_store

_log = logging.getLogger("nuvatra")

_PUBLIC_IPV4_RE = re.compile(
    r"^(?!(10\.|127\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|0\.|255\.))" r"\d{1,3}(\.\d{1,3}){3}$"
)


def _redis_url_from_env() -> str:
    return (os.getenv("REDIS_URL") or "").strip()


def _parse_redis_url(url: str) -> tuple[str, str]:
    """Return (scheme, hostname) without userinfo; empty strings if invalid."""
    if not url:
        return "", ""
    try:
        parsed = urlparse(url)
    except Exception:
        return "", ""
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").strip()
    return scheme, host


def redis_url_scheme_ok(url: str) -> bool:
    scheme, _ = _parse_redis_url(url)
    return scheme in ("redis", "rediss")


def redis_host_looks_external(url: str) -> bool:
    """
    Heuristic: flag likely public/exposed Redis hosts.
    Does not flag localhost, private RFC1918, or *.render.com internal names.
    """
    _, host = _parse_redis_url(url)
    if not host:
        return False
    lowered = host.lower()
    if lowered in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return lowered == "0.0.0.0"
    if lowered.endswith(".render.com") or lowered.endswith(".onrender.com"):
        return False
    try:
        addr = ipaddress.ip_address(host)
        return not addr.is_private and not addr.is_loopback
    except ValueError:
        pass
    if _PUBLIC_IPV4_RE.match(host):
        return True
    return False


def _voice_state_backend_name() -> Literal["redis", "memory"]:
    store = get_call_session_store()
    return "redis" if isinstance(store, RedisCallSessionStore) else "memory"


def _ping_redis(url: str) -> bool:
    if not url or not redis_url_scheme_ok(url):
        return False
    try:
        client = create_redis_client(url)
        try:
            return client.ping() is True
        finally:
            client.close()
    except Exception as e:
        _log.warning("redis_ops_ping_failed err=%s", type(e).__name__)
        return False


def redis_ops_health() -> dict[str, bool | str]:
    """
    Safe telemetry for admin ops panel — never includes URL, hostname, or password.
    """
    url = _redis_url_from_env()
    url_set = bool(url)
    scheme_ok = redis_url_scheme_ok(url) if url_set else False
    backend = _voice_state_backend_name()
    ping_ok = _ping_redis(url) if url_set and scheme_ok else False
    config_consistent = (not url_set) or backend == "redis"
    host_external = redis_host_looks_external(url) if url_set else False
    production_ready = (
        url_set
        and scheme_ok
        and ping_ok
        and backend == "redis"
        and config_consistent
    )
    return {
        "redis_url_set": url_set,
        "redis_url_scheme_ok": scheme_ok,
        "redis_ping_ok": ping_ok,
        "voice_state_backend": backend,
        "redis_config_consistent": config_consistent,
        "redis_host_looks_external": host_external,
        "redis_production_ready": production_ready,
    }
