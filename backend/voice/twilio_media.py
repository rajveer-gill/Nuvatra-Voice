"""Parse Twilio Media Streams WebSocket JSON messages."""

from __future__ import annotations

import base64
import json
from typing import Any, Optional


def parse_twilio_media_message(raw: str, max_bytes: int = 65536) -> Optional[dict[str, Any]]:
    if not raw or len(raw) > max_bytes:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def twilio_media_payload_bytes(media: dict[str, Any], max_b64_len: int = 12000) -> Optional[bytes]:
    """Decode base64 `payload` from a Twilio `media` event."""
    if media.get("event") != "media":
        return None
    inner = media.get("media")
    if not isinstance(inner, dict):
        return None
    b64 = inner.get("payload")
    if not isinstance(b64, str) or len(b64) > max_b64_len:
        return None
    pad = "=" * (-len(b64) % 4)
    try:
        return base64.b64decode(b64 + pad, validate=True)
    except Exception:
        return None


def twilio_start_meta(start_msg: dict[str, Any]) -> tuple[Optional[str], Optional[str], dict[str, str]]:
    """Return (call_sid, stream_sid, custom_parameters) from a `start` event."""
    if start_msg.get("event") != "start":
        return None, None, {}
    inner = start_msg.get("start")
    if not isinstance(inner, dict):
        return None, None, {}
    call_sid = inner.get("callSid") or inner.get("callsid")
    stream_sid = inner.get("streamSid") or inner.get("streamsid")
    raw_cp = inner.get("customParameters") or inner.get("customparameters")
    out: dict[str, str] = {}
    if isinstance(raw_cp, dict):
        for k, v in raw_cp.items():
            if isinstance(k, str) and isinstance(v, str) and len(k) < 200 and len(v) < 2000:
                out[k] = v
    cs = str(call_sid).strip() if call_sid else None
    ss = str(stream_sid).strip() if stream_sid else None
    return cs or None, ss or None, out
