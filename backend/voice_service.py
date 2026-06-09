"""Voice service — phone/voice domain logic lifted out of main.py.

Cut 1: recording-gating (plan + env) and phone-greeting payload composition. These are
shared by the phone routes (still in main), the business-info / greeting-preview routes,
and the call-recording proxy, so they're re-exported from main. Helpers are module-
qualified (database / config_service / deps / plans) per the strangler-fig discipline.
"""

from __future__ import annotations

import os
from typing import List, Optional

import config_service
import database
import deps
import runtime
from observability import voice_info, voice_trace

try:
    from plans import get_plan_limits
except ImportError:  # pragma: no cover
    get_plan_limits = None  # type: ignore


RECORDING_DISCLOSURE_TEXT = "This call may be recorded for quality and training."

DEFAULT_GREETING_TEMPLATE = (
    "Thank you for calling {business_name}. How can I help you today?"
)


def _greeting_debug_enabled() -> bool:
    """GREETING_DEBUG=1 or SETTINGS_LOAD_DEBUG=1 — logs greeting resolution on calls and Settings saves."""
    return deps._settings_load_debug_enabled() or os.getenv(
        "GREETING_DEBUG", ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _call_recording_env_enabled() -> bool:
    return os.getenv("CALL_RECORDING_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _tenant_for_call_recording(tenant: Optional[dict] = None) -> Optional[dict]:
    """Resolve tenant dict for plan-gated recording (explicit tenant or current client)."""
    if tenant:
        return tenant
    if not runtime.USE_DB:
        return None
    cid = database._client_id()
    if cid and cid != "default":
        return database.db_tenant_get_by_client_id(cid)
    return None


def _call_recording_enabled_for_tenant(tenant: Optional[dict] = None) -> bool:
    """Env flag AND Pro-tier plan (trial uses effective Pro limits via get_plan_limits)."""
    if not _call_recording_env_enabled():
        return False
    t = _tenant_for_call_recording(tenant)
    if not t or not get_plan_limits:
        return False
    return bool(get_plan_limits(t).get("has_call_recording"))


def _call_recording_enabled() -> bool:
    """Backward-compatible alias when tenant context is resolved from request client."""
    return _call_recording_enabled_for_tenant(None)


def _call_summary_enabled_for_tenant(tenant: Optional[dict] = None) -> bool:
    raw = os.getenv("CALL_SUMMARY_ENABLED")
    if raw is None or not str(raw).strip():
        return _call_recording_enabled_for_tenant(tenant)
    if not str(raw).strip().lower() in ("1", "true", "yes"):
        return False
    return _call_recording_enabled_for_tenant(tenant)


def _format_greeting_template(raw: str, info: dict) -> str:
    """Substitute {business_name} and {receptionist_name} in custom greeting text."""
    business_name = (info.get("name") or "us").strip() or "us"
    receptionist_name = (info.get("receptionist_name") or "").strip()
    subs = {"business_name": business_name, "receptionist_name": receptionist_name}
    try:
        return raw.format(**subs)
    except KeyError:
        out = raw
        for key, val in subs.items():
            out = out.replace("{" + key + "}", val)
        return out


def _resolve_greeting_business_name(info: dict, tenant: Optional[dict] = None) -> str:
    """Business name for {business_name} — config first, then tenant row from admin."""
    name = (info.get("name") or "").strip()
    if name:
        return name
    if tenant:
        name = (tenant.get("name") or "").strip()
        if name:
            return name
    cid = database._client_id()
    if runtime.USE_DB and cid:
        t = database.db_tenant_get_by_client_id(cid)
        if t:
            name = (t.get("name") or "").strip()
            if name:
                return name
    return "us"


def build_phone_greeting_payload(info: dict, tenant: Optional[dict] = None) -> dict:
    """
    Build phone greeting text: main message first, recording disclosure always last when enabled.
    Returns a debug-friendly dict (used by get_greeting_text and GET /api/greeting-preview).
    """
    cid = (database._client_id() or (tenant or {}).get("client_id") or "").strip()
    raw_saved = (info.get("greeting") or "").strip()
    used_default_template = not bool(raw_saved)
    raw_template = raw_saved if raw_saved else DEFAULT_GREETING_TEMPLATE

    business_name = _resolve_greeting_business_name(info, tenant)
    receptionist_name = (info.get("receptionist_name") or "").strip()
    fmt_info = {**info, "name": business_name, "receptionist_name": receptionist_name}
    main_greeting = _format_greeting_template(raw_template, fmt_info).strip()

    prepended_receptionist = False
    if receptionist_name and receptionist_name.lower() not in main_greeting.lower():
        main_greeting = f"Hi, I'm {receptionist_name}. {main_greeting}"
        prepended_receptionist = True

    tenant_rec = tenant if tenant is not None else _tenant_for_call_recording()
    recording_enabled = _call_recording_enabled_for_tenant(tenant_rec)
    recording_disclosure = RECORDING_DISCLOSURE_TEXT if recording_enabled else ""
    spoken_text = (
        f"{main_greeting} {recording_disclosure}".strip()
        if recording_disclosure
        else main_greeting
    )

    warnings: List[str] = []
    if "{receptionist_name}" in raw_template and not receptionist_name:
        warnings.append(
            "Greeting uses {receptionist_name} but AI receptionist name is empty in Settings."
        )
    if (
        "{business_name}" in raw_template
        and business_name == "us"
        and not (info.get("name") or "").strip()
    ):
        warnings.append(
            "Greeting uses {business_name} but business name is empty in Settings (using fallback 'us')."
        )

    return {
        "spoken_text": spoken_text,
        "main_greeting": main_greeting,
        "recording_disclosure": recording_disclosure or None,
        "used_default_template": used_default_template,
        "raw_greeting_saved": raw_saved,
        "prepended_receptionist": prepended_receptionist,
        "placeholders": {
            "business_name": business_name,
            "receptionist_name": receptionist_name,
        },
        "recording_enabled": recording_enabled,
        "config_source": config_service.client_config_source(cid) if cid else "none",
        "client_id": cid,
        "voice": (info.get("voice") or "fable") or "fable",
        "warnings": warnings,
    }


def _log_greeting_debug(
    event: str, payload: dict, *, call_sid: str = "", cache_hit: Optional[bool] = None
) -> None:
    """Structured greeting logs (Render: GREETING_DEBUG=1 or OBS_TRACE_VOICE=1)."""
    cid = (payload.get("client_id") or "")[:12]
    fields = {
        "client_id_prefix": cid or "(none)",
        "config_source": payload.get("config_source"),
        "used_default_template": payload.get("used_default_template"),
        "recording_enabled": payload.get("recording_enabled"),
        "prepended_receptionist": payload.get("prepended_receptionist"),
        "raw_greeting_len": len(payload.get("raw_greeting_saved") or ""),
        "spoken_len": len(payload.get("spoken_text") or ""),
        "business_name": (payload.get("placeholders") or {}).get("business_name"),
        "receptionist_name": (payload.get("placeholders") or {}).get(
            "receptionist_name"
        ),
        "voice": payload.get("voice"),
    }
    if call_sid:
        fields["call_sid"] = call_sid
    if cache_hit is not None:
        fields["cache_hit"] = cache_hit
    if payload.get("warnings"):
        fields["warnings"] = "; ".join(payload["warnings"])
    # Spoken text is not secret — needed to verify placeholders on production calls.
    spoken = (payload.get("spoken_text") or "")[:500]
    fields["spoken_preview"] = spoken
    voice_trace(event, **fields)
    if _greeting_debug_enabled():
        voice_info(event, **fields)
