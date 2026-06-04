"""Shared voice call session state (memory or Redis)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from urllib.parse import urlparse

from voice.call_sid import is_valid_call_sid, normalize_call_sid

_log = logging.getLogger("nuvatra")

SESSION_TTL_SEC = 30 * 60
UTTERANCE_LOCK_TTL_SEC = 45
MAX_SESSION_JSON_BYTES = 512_000


class UtteranceLockError(RuntimeError):
    """Raised when a distributed utterance lock cannot be acquired (fail-closed)."""


def _reject_invalid_call_sid(call_sid: str) -> None:
    if not is_valid_call_sid(call_sid):
        raise ValueError("invalid call_sid")


def _loads_session(raw: str) -> Optional[dict[str, Any]]:
    if len(raw.encode("utf-8", errors="replace")) > MAX_SESSION_JSON_BYTES:
        _log.warning("call_session_json_oversize bytes=%s", len(raw))
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class CallSessionStore(ABC):
    @abstractmethod
    def exists(self, call_sid: str) -> bool: ...

    @abstractmethod
    def get(self, call_sid: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def create(self, call_sid: str, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def save(self, call_sid: str, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete(self, call_sid: str) -> None: ...

    @abstractmethod
    def list_call_sids(self) -> list[str]: ...

    @abstractmethod
    def incr_media_stream_gen(self, call_sid: str) -> int: ...

    @abstractmethod
    def get_media_stream_max_gen(self, call_sid: str) -> int: ...

    @abstractmethod
    def get_response_status(self, call_sid: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def set_response_status(self, call_sid: str, status: dict[str, Any]) -> None: ...

    @abstractmethod
    def pop_response_status(self, call_sid: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def cleanup_call(self, call_sid: str) -> None: ...

    @asynccontextmanager
    async def utterance_lock(self, call_sid: str) -> AsyncIterator[None]:
        yield


class MemoryCallSessionStore(CallSessionStore):
    """Process-local store for dev and single-worker deployments."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.response_status: dict[str, dict[str, Any]] = {}
        self._utterance_locks: dict[str, asyncio.Lock] = {}

    def exists(self, call_sid: str) -> bool:
        sid = normalize_call_sid(call_sid)
        return bool(sid) and sid in self.sessions

    def get(self, call_sid: str) -> Optional[dict[str, Any]]:
        sid = normalize_call_sid(call_sid)
        if not sid:
            return None
        return self.sessions.get(sid)

    def create(self, call_sid: str, data: dict[str, Any]) -> None:
        sid = normalize_call_sid(call_sid)
        _reject_invalid_call_sid(sid)
        self.sessions[sid] = data

    def save(self, call_sid: str, data: dict[str, Any]) -> None:
        sid = normalize_call_sid(call_sid)
        _reject_invalid_call_sid(sid)
        self.sessions[sid] = data

    def delete(self, call_sid: str) -> None:
        sid = normalize_call_sid(call_sid)
        if sid:
            self.sessions.pop(sid, None)

    def list_call_sids(self) -> list[str]:
        return list(self.sessions.keys())

    def incr_media_stream_gen(self, call_sid: str) -> int:
        sid = normalize_call_sid(call_sid)
        session = self.sessions.get(sid) if sid else None
        if not session:
            return 0
        g = int(session.get("media_stream_gen") or 0) + 1
        session["media_stream_gen"] = g
        return g

    def get_media_stream_max_gen(self, call_sid: str) -> int:
        sid = normalize_call_sid(call_sid)
        if not sid:
            return 0
        session = self.sessions.get(sid)
        return int((session or {}).get("media_stream_gen") or 0)

    def get_response_status(self, call_sid: str) -> Optional[dict[str, Any]]:
        sid = normalize_call_sid(call_sid)
        return self.response_status.get(sid) if sid else None

    def set_response_status(self, call_sid: str, status: dict[str, Any]) -> None:
        sid = normalize_call_sid(call_sid)
        _reject_invalid_call_sid(sid)
        self.response_status[sid] = status

    def pop_response_status(self, call_sid: str) -> Optional[dict[str, Any]]:
        sid = normalize_call_sid(call_sid)
        return self.response_status.pop(sid, None) if sid else None

    def cleanup_call(self, call_sid: str) -> None:
        sid = normalize_call_sid(call_sid)
        if not sid:
            return
        self.sessions.pop(sid, None)
        self.response_status.pop(sid, None)
        self._utterance_locks.pop(sid, None)

    @asynccontextmanager
    async def utterance_lock(self, call_sid: str) -> AsyncIterator[None]:
        sid = normalize_call_sid(call_sid)
        if not sid:
            raise UtteranceLockError("invalid call_sid")
        lk = self._utterance_locks.get(sid)
        if lk is None:
            lk = asyncio.Lock()
            self._utterance_locks[sid] = lk
        async with lk:
            yield


class _SessionsProxy:
    """Dict-like view over Redis session keys for legacy active_calls access."""

    def __init__(self, store: "RedisCallSessionStore") -> None:
        self._store = store

    def __contains__(self, call_sid: object) -> bool:
        return isinstance(call_sid, str) and self._store.exists(call_sid)

    def __getitem__(self, call_sid: str) -> dict[str, Any]:
        data = self._store.get(call_sid)
        if data is None:
            raise KeyError(call_sid)
        return data

    def __setitem__(self, call_sid: str, data: dict[str, Any]) -> None:
        if self._store.exists(call_sid):
            self._store.save(call_sid, data)
        else:
            self._store.create(call_sid, data)

    def get(self, call_sid: str, default: Any = None) -> Any:
        data = self._store.get(call_sid)
        return data if data is not None else default

    def pop(self, call_sid: str, default: Any = None) -> Any:
        data = self._store.get(call_sid)
        if data is None:
            return default
        self._store.delete(call_sid)
        return data

    def items(self):
        for sid in self._store.list_call_sids():
            data = self._store.get(sid)
            if data is not None:
                yield sid, data

    def __len__(self) -> int:
        return len(self._store.list_call_sids())


class _ResponseStatusProxy:
    def __init__(self, store: "RedisCallSessionStore") -> None:
        self._store = store

    def __contains__(self, call_sid: object) -> bool:
        return isinstance(call_sid, str) and self._store.get_response_status(call_sid) is not None

    def __getitem__(self, call_sid: str) -> dict[str, Any]:
        data = self._store.get_response_status(call_sid)
        if data is None:
            raise KeyError(call_sid)
        return data

    def __setitem__(self, call_sid: str, status: dict[str, Any]) -> None:
        self._store.set_response_status(call_sid, status)

    def get(self, call_sid: str, default: Any = None) -> Any:
        data = self._store.get_response_status(call_sid)
        return data if data is not None else default

    def pop(self, call_sid: str, default: Any = None) -> Any:
        data = self._store.pop_response_status(call_sid)
        return data if data is not None else default


def create_redis_client(redis_url: str):
    """Create a Redis client with timeouts; enforce TLS cert verify for rediss://."""
    import redis

    scheme = (urlparse(redis_url).scheme or "").lower()
    kwargs: dict[str, Any] = {
        "decode_responses": True,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
    }
    if scheme == "rediss":
        kwargs["ssl_cert_reqs"] = "required"
    return redis.from_url(redis_url, **kwargs)


class RedisCallSessionStore(CallSessionStore):
    """Redis-backed store for multi-worker voice runtime."""

    def __init__(self, redis_url: str) -> None:
        self._redis = create_redis_client(redis_url)
        self._local_locks: dict[str, asyncio.Lock] = {}
        self.sessions = _SessionsProxy(self)
        self.response_status = _ResponseStatusProxy(self)

    def _session_key(self, call_sid: str) -> str:
        sid = normalize_call_sid(call_sid)
        if not sid:
            raise ValueError("invalid call_sid")
        return f"call:{sid}"

    def _resp_key(self, call_sid: str) -> str:
        return f"{self._session_key(call_sid)}:resp"

    def _lock_key(self, call_sid: str) -> str:
        return f"{self._session_key(call_sid)}:ulock"

    def _mgen_key(self, call_sid: str) -> str:
        return f"{self._session_key(call_sid)}:mgen"

    def _touch(self, key: str) -> None:
        self._redis.expire(key, SESSION_TTL_SEC)

    def exists(self, call_sid: str) -> bool:
        sid = normalize_call_sid(call_sid)
        if not sid:
            return False
        return bool(self._redis.exists(self._session_key(sid)))

    def get(self, call_sid: str) -> Optional[dict[str, Any]]:
        sid = normalize_call_sid(call_sid)
        if not sid:
            return None
        key = self._session_key(sid)
        raw = self._redis.get(key)
        if not raw:
            return None
        self._touch(key)
        return _loads_session(raw)

    def create(self, call_sid: str, data: dict[str, Any]) -> None:
        sid = normalize_call_sid(call_sid)
        _reject_invalid_call_sid(sid)
        payload = json.dumps(data)
        if len(payload.encode("utf-8")) > MAX_SESSION_JSON_BYTES:
            raise ValueError("session payload too large")
        key = self._session_key(sid)
        self._redis.set(key, payload, ex=SESSION_TTL_SEC)

    def save(self, call_sid: str, data: dict[str, Any]) -> None:
        self.create(call_sid, data)

    def delete(self, call_sid: str) -> None:
        sid = normalize_call_sid(call_sid)
        if not sid:
            return
        self._redis.delete(
            self._session_key(sid),
            self._resp_key(sid),
            self._lock_key(sid),
            self._mgen_key(sid),
        )

    def list_call_sids(self) -> list[str]:
        out: list[str] = []
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor=cursor, match="call:CA*", count=200)
            for key in keys:
                if key.count(":") != 1:
                    continue
                sid = key.split(":", 1)[1]
                if is_valid_call_sid(sid):
                    out.append(sid)
            if cursor == 0:
                break
        return out

    def incr_media_stream_gen(self, call_sid: str) -> int:
        sid = normalize_call_sid(call_sid)
        if not sid or not self.exists(sid):
            return 0
        mgen_key = self._mgen_key(sid)
        g = int(self._redis.incr(mgen_key))
        self._redis.expire(mgen_key, SESSION_TTL_SEC)
        session = self.get(sid)
        if session is not None:
            session["media_stream_gen"] = g
            self.save(sid, session)
        return g

    def get_media_stream_max_gen(self, call_sid: str) -> int:
        sid = normalize_call_sid(call_sid)
        if not sid:
            return 0
        raw = self._redis.get(self._mgen_key(sid))
        if raw is not None:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                pass
        session = self.get(sid)
        return int((session or {}).get("media_stream_gen") or 0)

    def get_response_status(self, call_sid: str) -> Optional[dict[str, Any]]:
        sid = normalize_call_sid(call_sid)
        if not sid:
            return None
        key = self._resp_key(sid)
        raw = self._redis.get(key)
        if not raw:
            return None
        self._touch(key)
        return _loads_session(raw)

    def set_response_status(self, call_sid: str, status: dict[str, Any]) -> None:
        sid = normalize_call_sid(call_sid)
        _reject_invalid_call_sid(sid)
        key = self._resp_key(sid)
        payload = json.dumps(status)
        if len(payload.encode("utf-8")) > MAX_SESSION_JSON_BYTES:
            raise ValueError("response status payload too large")
        self._redis.set(key, payload, ex=SESSION_TTL_SEC)

    def pop_response_status(self, call_sid: str) -> Optional[dict[str, Any]]:
        sid = normalize_call_sid(call_sid)
        if not sid:
            return None
        key = self._resp_key(sid)
        pipe = self._redis.pipeline()
        pipe.get(key)
        pipe.delete(key)
        raw, _ = pipe.execute()
        if not raw:
            return None
        return _loads_session(raw)

    def cleanup_call(self, call_sid: str) -> None:
        self.delete(call_sid)
        sid = normalize_call_sid(call_sid)
        if sid:
            self._local_locks.pop(sid, None)

    @asynccontextmanager
    async def utterance_lock(self, call_sid: str) -> AsyncIterator[None]:
        sid = normalize_call_sid(call_sid)
        if not sid:
            raise UtteranceLockError("invalid call_sid")
        deadline = time.monotonic() + 5.0
        acquired = False
        lock_key = self._lock_key(sid)
        while time.monotonic() < deadline:
            if self._redis.set(lock_key, "1", nx=True, ex=UTTERANCE_LOCK_TTL_SEC):
                acquired = True
                break
            await asyncio.sleep(0.05)
        if not acquired:
            _log.warning("redis_utterance_lock_timeout call_sid=%s", sid[:8])
            raise UtteranceLockError(sid)
        try:
            yield
        finally:
            self._redis.delete(lock_key)


_store: Optional[CallSessionStore] = None


def get_call_session_store() -> CallSessionStore:
    global _store
    if _store is not None:
        return _store
    backend = (os.getenv("VOICE_STATE_BACKEND") or "").strip().lower()
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if backend == "redis" or (backend != "memory" and redis_url):
        try:
            _store = RedisCallSessionStore(redis_url)
            _log.info("voice_call_session_store=redis")
            return _store
        except Exception as e:
            _log.warning("redis_call_session_store_failed fallback=memory err=%s", type(e).__name__)
    _store = MemoryCallSessionStore()
    _log.info("voice_call_session_store=memory")
    return _store


def reset_call_session_store_for_tests(store: Optional[CallSessionStore] = None) -> None:
    """Test helper to inject or reset the global store and rebind main.py aliases."""
    global _store
    _store = store if store is not None else MemoryCallSessionStore()
    try:
        import main as m

        m.call_store = _store
        m.active_calls = _store.sessions
        m.response_status = _store.response_status
    except ImportError:
        pass
