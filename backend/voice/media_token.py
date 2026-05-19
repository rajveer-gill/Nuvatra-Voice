"""HMAC-signed tokens for Twilio Media Stream WebSocket custom parameters."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional

from voice.stt_config import media_stream_signing_secret


def mint_media_stream_token(
    call_sid: str,
    ttl_sec: int = 3600,
    *,
    stream_generation: Optional[int] = None,
) -> str:
    """Opaque token Twilio echoes in the stream `start` customParameters."""
    secret = media_stream_signing_secret()
    if not secret or not call_sid:
        return ""
    exp = int(time.time()) + max(60, min(int(ttl_sec), 86400))
    body: dict[str, Any] = {"cs": call_sid, "e": exp}
    if stream_generation is not None:
        body["g"] = int(stream_generation)
    payload = json.dumps(body, separators=(",", ":"))
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = payload.encode("utf-8") + b"|" + sig.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_media_stream_token(
    token: str,
    expected_call_sid: str,
    *,
    expected_stream_generation: Optional[int] = None,
) -> bool:
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
    tok_gen = payload.get("g")
    if expected_stream_generation is not None:
        if not isinstance(tok_gen, (int, float)) or int(tok_gen) != int(expected_stream_generation):
            return False
    elif tok_gen is not None:
        # Generation-bound tokens must be verified with the expected generation.
        return False
    expect_sig = hmac.new(secret.encode("utf-8"), payload_b, hashlib.sha256).hexdigest()
    try:
        got = sig_b.decode("ascii")
    except Exception:
        return False
    return hmac.compare_digest(expect_sig, got)


def _decode_token_payload(token: str) -> Optional[dict[str, Any]]:
    if not token:
        return None
    pad = "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode(token + pad)
        if b"|" not in decoded:
            return None
        payload_b = decoded.split(b"|", 1)[0]
        payload: Any = json.loads(payload_b.decode("utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def token_call_sid_preview(token: str) -> Optional[str]:
    """Decode call_sid from token without verifying (logging only)."""
    payload = _decode_token_payload(token)
    if not payload:
        return None
    return str(payload.get("cs") or "") or None


def token_stream_generation(token: str) -> Optional[int]:
    """Decode stream generation `g` from token without verifying (logging / routing)."""
    payload = _decode_token_payload(token)
    if not payload:
        return None
    g = payload.get("g")
    if isinstance(g, (int, float)):
        return int(g)
    return None


def verify_pending_media_stream_token(
    token: str,
    call_sid: str,
    *,
    max_issued_generation: int,
) -> bool:
    """
    Accept a stream token for any generation up to ``max_issued_generation``.

    Incoming TwiML may mint tokens for multiple queued <Connect><Stream> verbs (g=1, g=2)
    before the first WebSocket connects; verification must not require the latest gen only.
    """
    g = token_stream_generation(token)
    if g is None or g < 1 or g > int(max_issued_generation):
        return False
    return verify_media_stream_token(token, call_sid, expected_stream_generation=g)
