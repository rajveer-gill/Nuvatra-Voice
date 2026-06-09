"""Voice service — phone/voice domain logic lifted out of main.py.

Cut 1: recording-gating (plan + env) and phone-greeting payload composition. These are
shared by the phone routes (still in main), the business-info / greeting-preview routes,
and the call-recording proxy, so they're re-exported from main. Helpers are module-
qualified (database / config_service / deps / plans) per the strangler-fig discipline.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import Request

import config_service
import database
import runtime
import deps
from observability import voice_info, voice_trace, voice_warning
from security.redaction import mask_phone_e164
from voice_preview import add_sentence_pauses
from voice.call_session_store import MemoryCallSessionStore

try:
    from plans import get_plan_limits
except ImportError:  # pragma: no cover
    get_plan_limits = None  # type: ignore

try:
    from twilio.request_validator import RequestValidator as _RequestValidator  # noqa: F401
    TWILIO_AVAILABLE = True
except ImportError:  # pragma: no cover
    TWILIO_AVAILABLE = False

logger = logging.getLogger("nuvatra")

# Self-computed (same value as main/config_service) so voice_service has no main dependency.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

RECORDING_DISCLOSURE_TEXT = "This call may be recorded for quality and training."

DEFAULT_GREETING_TEMPLATE = (
    "Thank you for calling {business_name}. How can I help you today?"
)

GOT_IT_PHRASE = "Got it, one moment."
ONE_MOMENT_PHRASE = "One moment."

# Fallback when OpenAI/TTS fails - play this so caller does not get dead air.
TTS_FALLBACK_TEXT = (
    "We're experiencing a brief technical issue. Please try again in a moment."
)


def cleanup_call_runtime_state(call_sid: str) -> None:
    """Clear per-call runtime state deterministically."""
    if not call_sid:
        return
    runtime.call_store.cleanup_call(call_sid)


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


# ===== STT provider selection (cut 3) =====


def _voice_stt_use_deepgram() -> bool:
    """Nova-2 live STT via Twilio Media Streams when env and credentials are present."""
    try:
        from voice.stt_runtime import deepgram_stt_active
    except ImportError:
        return False
    return deepgram_stt_active(
        twilio_available=TWILIO_AVAILABLE, twilio_client=runtime.twilio_client
    )


def uses_non_latin_script(language_name: str) -> bool:
    """
    Check if a language uses a non-Latin script (where Twilio transcription struggles).
    Returns True for languages like Japanese, Punjabi, Chinese, Arabic, Hindi, etc.
    """
    non_latin_languages = {
        "Japanese",
        "Punjabi",
        "Chinese",
        "Hindi",
        "Arabic",
        "Russian",
        "Korean",
        "Thai",
        "Vietnamese",
        "Bengali",
        "Tamil",
        "Telugu",
        "Gujarati",
        "Kannada",
        "Malayalam",
        "Marathi",
        "Urdu",
        "Hebrew",
        "Greek",
        "Georgian",
        "Armenian",
        "Khmer",
        "Lao",
        "Myanmar",
        "Tibetan",
        "Mongolian",
        "Nepali",
        "Sinhala",
    }
    return language_name in non_latin_languages


def _text_looks_latin(text: str) -> bool:
    """True when transcript is mostly basic Latin letters (English booking phrases, names, etc.)."""
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if ord(c) < 128)
    return latin / len(letters) >= 0.85


def _conversation_prefers_english_stt(call_data: dict) -> bool:
    """Use Deepgram/Gather English path when recent caller speech is Latin script."""
    lang = (call_data.get("detected_language") or "English").strip()
    if lang == "English" or not uses_non_latin_script(lang):
        return True
    for msg in reversed(call_data.get("conversation_history") or []):
        if msg.get("role") == "user":
            return _text_looks_latin(str(msg.get("content") or ""))
    return False


# ===== call-session context (cut 4; uses runtime.call_store) =====


def _persist_call_session(call_sid: str, data: Optional[dict] = None) -> None:
    """Write session back to Redis after in-place mutations (no-op for memory store)."""
    if isinstance(runtime.call_store, MemoryCallSessionStore):
        return
    sid = (call_sid or "").strip()
    if not sid or not runtime.call_store.exists(sid):
        return
    payload = data if data is not None else runtime.call_store.get(sid)
    if payload is not None:
        runtime.call_store.save(sid, payload)


def _merge_call_session(call_sid: str, updates: dict[str, Any]) -> None:
    """Persist partial session updates (safe on Redis and memory)."""
    if not call_sid or not updates:
        return
    runtime.call_store.merge_session(call_sid, updates)


def _call_sid_from_form(form_data: Any) -> str:
    """Normalize Twilio CallSid from webhook form body; empty string if invalid."""
    from voice.call_sid import normalize_call_sid

    return normalize_call_sid(str(form_data.get("CallSid") or "").strip())


def _restore_call_context(call_sid: str) -> bool:
    """Restore request client_id from call session for downstream phone handlers. Returns True if found."""
    if call_sid and runtime.call_store.exists(call_sid):
        cid = str((runtime.call_store.get(call_sid) or {}).get("client_id") or "").strip()
        if not cid:
            return False
        database.set_request_client_id(cid)
        return True
    return False


def _get_client_id_from_call(request: Request) -> Optional[str]:
    """Resolve client_id from call_sid query param (call session)."""
    call_sid = request.query_params.get("call_sid")
    if call_sid and runtime.call_store.exists(call_sid):
        return (
            str((runtime.call_store.get(call_sid) or {}).get("client_id") or "").strip() or None
        )
    return None


# ===== call log (cut 5; in-memory + file/DB persistence) =====

call_log_entries = {}  # call_sid -> {from_number, to_number, start_iso, outcome, ...}

CALL_LOG_MAX_ENTRIES = 5000


def call_log_start(call_sid: str, from_number: str, to_number: str):
    """Record call start. Outcome set when we forward or in status callback."""
    call_log_entries[call_sid] = {
        "call_sid": call_sid,
        "from_number": from_number,
        "to_number": to_number,
        "start_iso": datetime.now().isoformat(),
        "outcome": None,
        "end_iso": None,
        "duration_sec": None,
        "category": None,
        "recording_sid": None,
        "recording_url": None,
        "recording_duration_sec": None,
        "recording_status": None,
        "call_summary": None,
    }
    deps.audit_log(
        "voice",
        "call_started",
        resource_type="call",
        resource_id=call_sid,
        client_id=database._client_id() if runtime.USE_DB else None,
        details={
            "from_masked": mask_phone_e164(from_number or ""),
            "to_masked": mask_phone_e164(to_number or ""),
        },
    )


def call_log_merge_recording(call_sid: str, **kwargs) -> None:
    """Merge recording / summary fields into in-memory call log entry."""
    ent = call_log_entries.get(call_sid)
    if not ent:
        return
    for k, v in kwargs.items():
        if v is not None:
            ent[k] = v


def _file_call_log_merge_recording(call_sid: str, **kwargs) -> None:
    """Best-effort merge into clients/<id>/call_log.json when not using DB."""
    data_dir = config_service.get_client_data_dir()
    if not data_dir:
        return
    path = data_dir / "call_log.json"
    log_list: List[dict] = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                log_list = json.load(f)
        except Exception:
            return
    for e in reversed(log_list):
        if e.get("call_sid") == call_sid:
            for k, v in kwargs.items():
                if v is not None:
                    e[k] = v
            break
    else:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(log_list, f, indent=2)
    except Exception as ex:
        print(f"Failed to merge recording into file call log: {ex}")


def call_log_set_outcome(call_sid: str, outcome: str):
    """Set outcome: 'forwarded', 'answered_by_ai', 'missed', 'error', 'no-answer'."""
    if call_sid in call_log_entries:
        call_log_entries[call_sid]["outcome"] = outcome


def call_log_end(call_sid: str):
    """Write completed call to persistent log and remove from in-memory."""
    if call_sid not in call_log_entries:
        return
    entry = call_log_entries[call_sid].copy()
    entry["end_iso"] = datetime.now().isoformat()
    start_s = entry.get("start_iso")
    if start_s:
        try:
            start_dt = datetime.fromisoformat(start_s.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(entry["end_iso"].replace("Z", "+00:00"))
            entry["duration_sec"] = int((end_dt - start_dt).total_seconds())
        except Exception:
            pass
    if not entry.get("outcome"):
        entry["outcome"] = "answered_by_ai"
    deps.audit_log(
        "voice",
        "call_ended",
        resource_type="call",
        resource_id=call_sid,
        client_id=database._client_id() if runtime.USE_DB else None,
        details={
            "outcome": entry.get("outcome"),
            "duration_sec": entry.get("duration_sec"),
            "recording_status": entry.get("recording_status"),
        },
    )
    if runtime.USE_DB:
        database.db_call_log_append(entry)
    else:
        data_dir = config_service.get_client_data_dir()
        if data_dir:
            path = data_dir / "call_log.json"
            log_list = []
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        log_list = json.load(f)
                except Exception:
                    pass
            log_list.append(entry)
            if len(log_list) > CALL_LOG_MAX_ENTRIES:
                log_list = log_list[-CALL_LOG_MAX_ENTRIES:]
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(log_list, f, indent=2)
            except Exception as e:
                print(f"Failed to save call log: {e}")
    del call_log_entries[call_sid]


# ===== call recording: SSRF-guarded fetch + Whisper/GPT summary (cut 6) =====


def _is_trusted_twilio_media_url(url: str) -> bool:
    """True only for https URLs on a Twilio-owned host.

    Recording/media URLs arrive in webhook bodies, which an attacker could forge
    if a signature check is ever bypassed. We never attach Twilio credentials to
    any other host — this is the SSRF / credential-exfil trust boundary, enforced
    at every credentialed fetch site below.
    """
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return host == "twilio.com" or host.endswith(".twilio.com")


def _fetch_twilio_recording_bytes(recording_url: str) -> tuple:
    import httpx

    if not _is_trusted_twilio_media_url(recording_url):
        logger.error("[Recording] Refusing to fetch recording from untrusted host")
        return 0, b""
    r = httpx.get(
        recording_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=120.0,
    )
    return r.status_code, r.content


def _summarize_call_recording_sync(
    call_sid: str, client_id: str, recording_url: str, duration_sec: Optional[int]
) -> None:
    """Download Twilio recording, Whisper transcribe, short GPT summary; persist call_summary."""
    if not recording_url or not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return
    if not _is_trusted_twilio_media_url(recording_url):
        logger.error(
            "[Recording] Refusing summary fetch from untrusted host call_sid=%s",
            call_sid,
        )
        return
    try:
        cap = int(os.getenv("CALL_SUMMARY_MAX_DURATION_SEC", "1800"))
    except ValueError:
        cap = 1800
    if duration_sec is not None and duration_sec > cap:
        logger.info(
            "[Recording] Skip summary (duration %s sec > cap %s)", duration_sec, cap
        )
        return
    if (os.getenv("TWILIO_INTELLIGENCE_SERVICE_SID") or "").strip():
        logger.info(
            "[Recording] TWILIO_INTELLIGENCE_SERVICE_SID is set; Phase 1 still uses OpenAI Whisper+GPT"
        )
    try:
        import httpx

        with httpx.Client(timeout=120.0) as http:
            r = http.get(recording_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        if r.status_code != 200:
            logger.error(
                "[Recording] Download failed status=%s call_sid=%s",
                r.status_code,
                call_sid,
            )
            return
        audio_data = r.content
        runtime._ensure_openai_client()
        bio = io.BytesIO(audio_data)
        bio.name = "recording.mp3"
        transcript = runtime.client.audio.transcriptions.create(model="whisper-1", file=bio)
        text = (getattr(transcript, "text", None) or "").strip()
        if not text:
            return
        resp = runtime.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Summarize this phone call in 2–4 clear sentences for a business owner dashboard. Mention caller intent (e.g. appointment, question, complaint) if clear. Be factual; do not invent details.",
                },
                {"role": "user", "content": text[:12000]},
            ],
            max_tokens=350,
            temperature=0.3,
        )
        summary = (resp.choices[0].message.content or "").strip()
        if not summary:
            return
        database.set_request_client_id(client_id)
        if runtime.USE_DB:
            database.db_call_log_update_summary(call_sid, client_id, summary)
        call_log_merge_recording(call_sid, call_summary=summary)
        if not runtime.USE_DB:
            _file_call_log_merge_recording(call_sid, call_summary=summary)
    except Exception:
        logger.exception("[Recording] Summarize failed call_sid=%s", call_sid)


async def _schedule_recording_summary(
    call_sid: str, client_id: str, recording_url: str, duration_sec: Optional[int]
) -> None:
    try:
        await asyncio.to_thread(
            _summarize_call_recording_sync,
            call_sid,
            client_id,
            recording_url,
            duration_sec,
        )
    except Exception:
        logger.exception("[Recording] Summary task failed call_sid=%s", call_sid)
