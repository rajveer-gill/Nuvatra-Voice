"""Persistent + in-memory cache for fixed voice clips (greeting, got-it filler)."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Literal, Optional

_log = logging.getLogger("nuvatra")

ClipKind = Literal["greeting", "got_it"]

_MEMORY: dict[ClipKind, dict[tuple, bytes]] = {
    "greeting": {},
    "got_it": {},
}


def _hash_key(cache_key: tuple) -> str:
    payload = json.dumps(cache_key, default=str, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def cache_dir_for_client(project_root: Path, client_id: str) -> Path:
    root = project_root / "clients" / client_id / "voice_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _disk_path(project_root: Path, kind: ClipKind, cache_key: tuple) -> Path:
    client_id = str(cache_key[0])
    return cache_dir_for_client(project_root, client_id) / f"{kind}_{_hash_key(cache_key)}.mp3"


def get_cached(project_root: Path, kind: ClipKind, cache_key: tuple) -> Optional[bytes]:
    mem = _MEMORY[kind].get(cache_key)
    if mem:
        return mem
    path = _disk_path(project_root, kind, cache_key)
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
        if data:
            _MEMORY[kind][cache_key] = data
            return data
    except OSError as e:
        _log.warning("[VOICE] tts_cache read failed kind=%s: %s", kind, e)
    return None


def put_cached(project_root: Path, kind: ClipKind, cache_key: tuple, data: bytes) -> None:
    if not data:
        return
    _MEMORY[kind][cache_key] = data
    path = _disk_path(project_root, kind, cache_key)
    try:
        path.write_bytes(data)
    except OSError as e:
        _log.warning("[VOICE] tts_cache write failed kind=%s: %s", kind, e)


def invalidate_client(project_root: Path, client_id: str) -> None:
    cid = (client_id or "").strip()
    if not cid:
        return
    for kind in ("greeting", "got_it"):
        for key in list(_MEMORY[kind].keys()):
            if isinstance(key, tuple) and key and key[0] == cid:
                _MEMORY[kind].pop(key, None)
    root = project_root / "clients" / cid / "voice_cache"
    if root.is_dir():
        for path in root.glob("*.mp3"):
            try:
                path.unlink()
            except OSError as e:
                _log.warning("[VOICE] tts_cache delete failed path=%s: %s", path, e)


def clear_all_memory() -> None:
    _MEMORY["greeting"].clear()
    _MEMORY["got_it"].clear()
