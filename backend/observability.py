"""
Production-oriented tracing for SMS, voice, webhooks, and usage.

Environment:
  LOG_LEVEL=INFO|DEBUG     — DEBUG enables verbose branches when combined with OBS_VERBOSE.
  OBS_VERBOSE=1            — Extra DEBUG logs inside SMS/voice/chat paths (slot checks, branches).
  OBS_TRACE_WEBHOOKS=1     — INFO log for each /api/phone/* and /api/sms/* request (timing + status).
  OBS_TRACE_SMS=1          — INFO logs each inbound SMS pipeline step (tenant resolve, compliance, AI, DB); use when debugging delivery or replies.

Phone numbers are masked in log lines (security.redaction).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Mapping, Optional

from security.redaction import mask_phone_e164

_log = logging.getLogger("nuvatra")


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


OBS_VERBOSE: bool = _truthy("OBS_VERBOSE")
OBS_TRACE_WEBHOOKS: bool = _truthy("OBS_TRACE_WEBHOOKS")
OBS_TRACE_SMS: bool = _truthy("OBS_TRACE_SMS")


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
