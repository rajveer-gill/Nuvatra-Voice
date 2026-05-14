"""HMAC-signed tokens for Twilio Media Stream WebSocket custom parameters."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional

from voice.stt_config import media_stream_signing_secret


def mint_media_stream_token(call_sid: str, ttl_sec: int = 3600) -> str:
    """Opaque token Twilio echoes in the stream `start` customParameters."""
    secret = media_stream_signing_secret()
    if not secret or not call_sid:
        return ""
    exp = int(time.time()) + max(60, min(int(ttl_sec), 86400))
    payload = json.dumps({"cs": call_sid, "e": exp}, separators=(",", ":"))
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = payload.encode("utf-8") + b"|" + sig.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_media_stream_token(token: str, expected_call_sid: str) -> bool:
    if not token or not expected_call_sid:
        return False
    secret = media_stream_signing_secret()
    if not secret:
        return False
    pad = "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode(token + pad)
    except Exception:
        return False
    if b"|" not in decoded:
        return False
    payload_b, sig_b = decoded.rsplit(b"|", 1)
    try:
        payload = json.loads(payload_b.decode("utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    if (payload.get("cs") or "") != expected_call_sid:
        return False
    exp = payload.get("e")
    if not isinstance(exp, (int, float)) or int(time.time()) > int(exp):
        return False
    expect_sig = hmac.new(secret.encode("utf-8"), payload_b, hashlib.sha256).hexdigest()
    try:
        got = sig_b.decode("ascii")
    except Exception:
        return False
    return hmac.compare_digest(expect_sig, got)


def token_call_sid_preview(token: str) -> Optional[str]:
    """Decode call_sid from token without verifying (logging only)."""
    if not token:
        return None
    pad = "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode(token + pad)
        payload_b = decoded.split(b"|", 1)[0]
        payload: Any = json.loads(payload_b.decode("utf-8"))
        if isinstance(payload, dict):
            return str(payload.get("cs") or "") or None
    except Exception:
        return None
    return None
