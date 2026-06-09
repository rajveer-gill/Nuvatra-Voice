"""Voice service — phone/voice domain logic lifted out of main.py.

Cut 1: recording-gating (plan + env) and phone-greeting payload composition. These are
shared by the phone routes (still in main), the business-info / greeting-preview routes,
and the call-recording proxy, so they're re-exported from main. Helpers are module-
qualified (database / config_service / deps / plans) per the strangler-fig discipline.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional

import config_service
import database
import runtime
import deps
from observability import voice_info, voice_trace, voice_warning
from voice_preview import add_sentence_pauses

try:
    from plans import get_plan_limits
except ImportError:  # pragma: no cover
    get_plan_limits = None  # type: ignore

logger = logging.getLogger("nuvatra")

# Self-computed (same value as main/config_service) so voice_service has no main dependency.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()

RECORDING_DISCLOSURE_TEXT = "This call may be recorded for quality and training."

DEFAULT_GREETING_TEMPLATE = (
    "Thank you for calling {business_name}. How can I help you today?"
)

GOT_IT_PHRASE = "Got it, one moment."
ONE_MOMENT_PHRASE = "One moment."


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


# ===== TTS synthesis + audio cache (cut 2) =====


def _got_it_cache_key(client_id: str) -> tuple:
    info = config_service.get_business_info()
    try:
        speed_key = round(float(info.get("speed", 1.0)), 2)
    except (TypeError, ValueError):
        speed_key = 1.0
    return (
        client_id,
        GOT_IT_PHRASE,
        (config_service.get_tts_voice() or "fable").strip(),
        speed_key,
    )


def _one_moment_cache_key(client_id: str) -> tuple:
    info = config_service.get_business_info()
    try:
        speed_key = round(float(info.get("speed", 1.0)), 2)
    except (TypeError, ValueError):
        speed_key = 1.0
    return (
        client_id,
        ONE_MOMENT_PHRASE,
        (config_service.get_tts_voice() or "fable").strip(),
        speed_key,
    )


def _synthesize_tts_clip(text: str, *, voice: str, speed: float) -> bytes:
    runtime._ensure_openai_client()
    resp = runtime.client.audio.speech.create(
        model="tts-1-hd",
        voice=voice,
        input=add_sentence_pauses(text),
        speed=max(0.25, min(4.0, float(speed))),
    )
    return resp.content


def _ensure_greeting_audio_cached(client_id: str) -> bool:
    """Ensure greeting clip exists in cache; synthesize on miss. Returns True when cached."""
    from voice.tts_cache import get_cached, put_cached

    cid = (client_id or "").strip()
    if not cid or cid == "default":
        return False
    database.set_request_client_id(cid)
    greeting_key = _greeting_audio_cache_key(cid)
    if get_cached(PROJECT_ROOT, "greeting", greeting_key):
        return True
    info = config_service.get_business_info()
    tenant = _tenant_for_call_recording()
    payload = build_phone_greeting_payload(info, tenant)
    voice = (payload.get("voice") or config_service.get_tts_voice() or "fable").strip()
    speed = config_service.get_tts_speed()
    data = _synthesize_tts_clip(payload["spoken_text"], voice=voice, speed=speed)
    put_cached(PROJECT_ROOT, "greeting", greeting_key, data)
    voice_info(
        "greeting_audio_prewarmed",
        client_id_prefix=cid[:12],
        voice=voice,
        bytes=len(data),
    )
    return True


def _warm_auxiliary_voice_cache(client_id: str) -> None:
    """Pre-generate got-it and one-moment clips (non-blocking for call answer)."""
    from voice.tts_cache import get_cached, put_cached

    cid = (client_id or "").strip()
    if not cid or cid == "default":
        return
    database.set_request_client_id(cid)
    got_it_key = _got_it_cache_key(cid)
    if not get_cached(PROJECT_ROOT, "got_it", got_it_key):
        voice = got_it_key[2]
        speed = got_it_key[3]
        data = _synthesize_tts_clip(GOT_IT_PHRASE, voice=voice, speed=speed)
        put_cached(PROJECT_ROOT, "got_it", got_it_key, data)
        voice_info(
            "got_it_audio_prewarmed",
            client_id_prefix=cid[:12],
            voice=voice,
            bytes=len(data),
        )
    one_moment_key = _one_moment_cache_key(cid)
    if not get_cached(PROJECT_ROOT, "one_moment", one_moment_key):
        voice = one_moment_key[2]
        speed = one_moment_key[3]
        data = _synthesize_tts_clip(ONE_MOMENT_PHRASE, voice=voice, speed=speed)
        put_cached(PROJECT_ROOT, "one_moment", one_moment_key, data)
        voice_info(
            "one_moment_audio_prewarmed",
            client_id_prefix=cid[:12],
            voice=voice,
            bytes=len(data),
        )


def warm_client_voice_cache(client_id: str) -> None:
    """Pre-generate greeting, got-it, and one-moment clips for a tenant."""
    cid = (client_id or "").strip()
    if not cid or cid == "default":
        return
    try:
        _ensure_greeting_audio_cached(cid)
        _warm_auxiliary_voice_cache(cid)
    except Exception as e:
        voice_warning(
            "voice_cache_prewarm_failed",
            client_id_prefix=cid[:12],
            error_type=type(e).__name__,
        )
        logger.warning(
            "warm_client_voice_cache failed client_id=%s: %s", cid, e, exc_info=True
        )


def _warm_all_tenant_voice_caches() -> None:
    """Prewarm voice clips at startup.

    Single-tenant/dev: warm the one configured runtime.client (cheap). Multi-tenant:
    sweeping every tenant at boot is O(tenants × 3 TTS calls) and does not scale
    (minutes of OpenAI calls at 60+ tenants, blocking nothing but burning quota
    and a worker). It is therefore LAZY by default — greeting/got-it/one-moment
    clips synthesize on the first call and are re-warmed on config save. Set
    VOICE_PREWARM_ALL_TENANTS=1 to opt into the full boot sweep for small fleets.
    """
    if not runtime.USE_DB:
        cid = (CLIENT_ID or "").strip()
        if cid and cid != "default":
            warm_client_voice_cache(cid)
        return
    if (os.getenv("VOICE_PREWARM_ALL_TENANTS") or "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        logger.info(
            "voice_cache_startup_prewarm skipped (lazy; set VOICE_PREWARM_ALL_TENANTS=1 to enable)"
        )
        return
    try:
        tenants = database.db_tenant_list_all()
    except Exception as e:
        logger.warning("voice_cache_startup_prewarm list failed: %s", e)
        return
    for tenant in tenants:
        cid = (tenant.get("client_id") or "").strip()
        phone = (tenant.get("twilio_phone_number") or "").strip()
        if not cid or not phone:
            continue
        try:
            warm_client_voice_cache(cid)
        except Exception as e:
            logger.warning(
                "voice_cache_startup_prewarm failed client_id=%s: %s", cid, e
            )


async def _warm_client_voice_cache_async(client_id: str) -> None:
    await asyncio.to_thread(warm_client_voice_cache, client_id)


async def _warm_auxiliary_voice_cache_async(client_id: str) -> None:
    await asyncio.to_thread(_warm_auxiliary_voice_cache, client_id)


def _greeting_audio_cache_key(client_id: str) -> tuple:
    """Cache key from fully resolved spoken text (includes tenant name fallback for placeholders)."""
    info = config_service.get_business_info()
    tenant = _tenant_for_call_recording()
    payload = build_phone_greeting_payload(info, tenant)
    try:
        speed_key = round(float(info.get("speed", 1.0)), 2)
    except (TypeError, ValueError):
        speed_key = 1.0
    return (
        client_id,
        payload["spoken_text"],
        (payload.get("voice") or "fable").strip(),
        speed_key,
    )
