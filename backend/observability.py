"""
Production-oriented tracing for SMS, voice, webhooks, and usage.

Environment:
  LOG_LEVEL=INFO|DEBUG     — DEBUG enables verbose branches when combined with OBS_VERBOSE.
  OBS_VERBOSE=1            — Extra DEBUG logs inside SMS/voice/chat paths (slot checks, branches).
  OBS_TRACE_WEBHOOKS=1     — INFO log for each /api/phone/* and /api/sms/* request (timing + status).
  OBS_TRACE_SMS=1          — INFO logs each inbound SMS pipeline step (tenant resolve, compliance, AI, DB); use when debugging delivery or replies.
  OBS_TRACE_VOICE=1        — INFO logs each voice pipeline step (incoming, respond branches, transfers, STT); recommended when debugging calls on Render.
  OBS_TRACE_TRANSCRIPT=1   — INFO logs the FULL caller and AI utterances (whole conversation). PII: contains raw transcript text, so keep OFF by default and enable only while actively debugging a call.
  GREETING_DEBUG=1         — INFO logs resolved phone greeting text (spoken_preview) on each call and Settings save; also enabled when SETTINGS_LOAD_DEBUG=1.
  VOICE_STT_PROVIDER=twilio|deepgram — Default twilio (Gather). deepgram uses Media Streams on every listen turn (/api/phone/media + Deepgram Nova-2); Gather remains fail-open fallback.
  DEEPGRAM_API_KEY         — Required when VOICE_STT_PROVIDER=deepgram.
  MEDIA_STREAM_SIGNING_SECRET — Optional HMAC secret for stream tokens; falls back to TWILIO_AUTH_TOKEN.
  VOICE_MEDIA_STREAM_MAX_SEC — Max seconds per Connect+Stream listening window (default 30).
  VOICE_DEEPGRAM_FINAL_DEBOUNCE_MS — Silence (ms) to wait after the caller stops before committing the utterance / playing "got it" (default 800). Higher = caller feels less rushed on pauses; too high = slower replies.

Phone numbers are masked in log lines (security.redaction).
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Mapping, Optional

from security.redaction import mask_phone_e164

_log = logging.getLogger("nuvatra")


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _stable_sha256(text: str) -> str:
    """Deterministic hex digest (idempotency keys, dedup, log correlation)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


OBS_VERBOSE: bool = _truthy("OBS_VERBOSE")
OBS_TRACE_WEBHOOKS: bool = _truthy("OBS_TRACE_WEBHOOKS")
OBS_TRACE_SMS: bool = _truthy("OBS_TRACE_SMS")
OBS_TRACE_VOICE: bool = _truthy("OBS_TRACE_VOICE")
OBS_TRACE_TRANSCRIPT: bool = _truthy("OBS_TRACE_TRANSCRIPT")


def name_initial_for_log(name: Optional[str]) -> str:
    """First letter only — enough to verify Jake→Raj without logging full names."""
    n = (name or "").strip()
    if not n:
        return "-"
    return n[0].upper()


def email_hint_for_log(email: Optional[str]) -> str:
    """Domain + local initial only (e.g. r***@gmail.com)."""
    e = (email or "").strip()
    if not e or "@" not in e:
        return "-"
    local, _, domain = e.partition("@")
    li = (local[:1] or "?") + "***"
    return f"{li}@{domain}"


def mask_phone(raw: Optional[str]) -> str:
    """Mask any Twilio-style phone string for logs."""
    if not raw:
        return "(none)"
    s = str(raw).strip()
    if not s:
        return "(none)"
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 10:
        return mask_phone_e164("+1" + digits)
    if len(digits) == 11 and digits.startswith("1"):
        return mask_phone_e164("+" + digits)
    if len(digits) >= 10:
        return mask_phone_e164("+" + digits[-10:])
    if len(s) >= 8:
        return mask_phone_e164(s)
    return "***"


_PHONE_SUBSTR = "phone"


def _format_fields(fields: Mapping[str, Any]) -> str:
    bits: list[str] = []
    for k, v in fields.items():
        if v is None:
            continue
        lk = str(k).lower()
        if lk in (
            "from",
            "to",
            "from_number",
            "to_number",
            "phone",
            "caller_phone",
            "recipient",
            "caller",
        ) or _PHONE_SUBSTR in lk:
            bits.append(f"{k}={mask_phone(str(v))}")
        elif lk == "body" and isinstance(v, str) and len(v) > 120:
            bits.append(f"{k}_len={len(v)}")
        else:
            bits.append(f"{k}={v}")
    return " ".join(bits)


def sms_event(level: int, event: str, **fields: Any) -> None:
    msg = _format_fields(fields)
    _log.log(level, "[SMS] %s | %s", event, msg)


def sms_info(event: str, **fields: Any) -> None:
    sms_event(logging.INFO, event, **fields)


def sms_debug(event: str, **fields: Any) -> None:
    if not OBS_VERBOSE:
        return
    sms_event(logging.DEBUG, event, **fields)


def sms_trace(event: str, **fields: Any) -> None:
    """Detailed inbound/outbound SMS pipeline steps at INFO when OBS_TRACE_SMS=1 (Render-friendly)."""
    if not OBS_TRACE_SMS:
        return
    sms_event(logging.INFO, event, **fields)


def voice_event(level: int, event: str, **fields: Any) -> None:
    msg = _format_fields(fields)
    _log.log(level, "[VOICE] %s | %s", event, msg)


def voice_info(event: str, **fields: Any) -> None:
    voice_event(logging.INFO, event, **fields)


def voice_debug(event: str, **fields: Any) -> None:
    if not OBS_VERBOSE:
        return
    voice_event(logging.DEBUG, event, **fields)


def voice_trace(event: str, **fields: Any) -> None:
    """Detailed voice pipeline steps at INFO when OBS_TRACE_VOICE=1 (Render-friendly)."""
    if not OBS_TRACE_VOICE:
        return
    voice_event(logging.INFO, event, **fields)


def voice_transcript(event: str, *, call_sid: str = "", text: str = "", **fields: Any) -> None:
    """Log a full caller/AI utterance at INFO when OBS_TRACE_TRANSCRIPT=1, so the whole
    conversation is reconstructable from the logs. PII: emits raw transcript text (capped to
    2000 chars), so keep the flag OFF except while actively debugging a call."""
    if not OBS_TRACE_TRANSCRIPT:
        return
    voice_event(
        logging.INFO,
        event,
        call_sid=call_sid,
        text=(text or "").strip()[:2000],
        **fields,
    )


def voice_warning(event: str, **fields: Any) -> None:
    voice_event(logging.WARNING, event, **fields)


def _client_prefix(client_id: Optional[str]) -> str:
    cid = (client_id or "").strip()
    return cid[:12] if cid else "(none)"


def voice_forward(
    reason: str,
    *,
    call_sid: str = "",
    client_id: str = "",
    forward_kind: str = "fallback",
    staff_name: str = "",
    has_fallback_configured: Optional[bool] = None,
    **extra: Any,
) -> None:
    """
    Log every live call transfer at INFO with a stable reason code (search Render logs for forward_decision).

    reason examples: staff_transfer_by_name, caller_requested_human, no_speech_timeout,
    respond_status_forward, incoming_error_forward, utterance_lost_session_forward.
    """
    fields: dict[str, Any] = {
        "reason": reason,
        "call_sid": call_sid or "",
        "client_id_prefix": _client_prefix(client_id),
        "forward_kind": forward_kind,
        **extra,
    }
    if staff_name:
        fields["staff_name"] = staff_name[:80]
    if has_fallback_configured is not None:
        fields["has_fallback_configured"] = has_fallback_configured
    voice_event(logging.INFO, "forward_decision", **fields)


def voice_respond_branch(
    branch: str,
    *,
    call_sid: str = "",
    client_id: str = "",
    status: str = "",
    **extra: Any,
) -> None:
    """Log /api/phone/respond TwiML branch (always INFO — critical for debugging stuck/early transfers)."""
    voice_event(
        logging.INFO,
        "respond_branch",
        branch=branch,
        call_sid=call_sid or "",
        client_id_prefix=_client_prefix(client_id),
        status=status or "",
        **extra,
    )


def voice_call_phase(
    phase: str,
    *,
    call_sid: str = "",
    client_id: str = "",
    **extra: Any,
) -> None:
    """High-level call lifecycle (incoming, greeting, utterance, gpt_ready, etc.)."""
    voice_trace(
        "call_phase",
        phase=phase,
        call_sid=call_sid or "",
        client_id_prefix=_client_prefix(client_id),
        **extra,
    )


def system_info(event: str, **fields: Any) -> None:
    msg = _format_fields(fields)
    _log.info("[SYSTEM] %s | %s", event, msg)


def system_debug(event: str, **fields: Any) -> None:
    if not OBS_VERBOSE:
        return
    msg = _format_fields(fields)
    _log.debug("[SYSTEM] %s | %s", event, msg)


def usage_warning(event: str, **fields: Any) -> None:
    msg = _format_fields(fields)
    _log.warning("[USAGE] %s | %s", event, msg)


def auth_warning(event: str, **fields: Any) -> None:
    msg = _format_fields(fields)
    _log.warning("[AUTH] %s | %s", event, msg)


def webhook_http_log(request_method: str, path: str, status_code: int, ms: float, request_id: str = "") -> None:
    _log.info(
        "[HTTP] %s %s -> %s %.1fms rid=%s",
        request_method,
        path,
        status_code,
        ms,
        request_id or "-",
    )


async def webhook_timing_middleware(request, call_next):
    """When OBS_TRACE_WEBHOOKS=1, log latency and status for Twilio webhook routes."""
    path = request.url.path
    if not OBS_TRACE_WEBHOOKS or not (
        path.startswith("/api/phone") or path.startswith("/api/sms")
    ):
        return await call_next(request)
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        rid = getattr(request.state, "request_id", "") or ""
        webhook_http_log(request.method, path, response.status_code, ms, rid)
        return response
    except Exception:
        ms = (time.perf_counter() - t0) * 1000
        rid = getattr(request.state, "request_id", "") or ""
        _log.exception("[HTTP] %s %s FAILED after %.1fms rid=%s", request.method, path, ms, rid)
        raise
