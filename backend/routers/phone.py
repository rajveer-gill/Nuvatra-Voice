"""Phone/voice routes — audio (TTS) endpoints.

Twilio fetches these for greeting/got-it/one-moment/arbitrary TTS clips. All voice helpers
now live in voice_service / config_service / deps; this router is a thin transport layer.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from caller_memory import get_caller_memory, refresh_caller_memory_for_prompt, update_caller_memory
import config_service
import conversation_service
import database
import deps
import runtime
import sms_service
import voice_service
from observability import (
    auth_warning,
    name_initial_for_log,
    sms_info,
    system_info,
    voice_call_phase,
    voice_debug,
    voice_forward,
    voice_info,
    voice_respond_branch,
    voice_trace,
    voice_warning,
)
from voice_preview import add_sentence_pauses

try:
    from twilio.twiml.voice_response import VoiceResponse
    TWILIO_AVAILABLE = True
except ImportError:  # pragma: no cover
    VoiceResponse = None  # type: ignore
    TWILIO_AVAILABLE = False

logger = logging.getLogger("nuvatra")
import os as _os
CLIENT_ID = _os.getenv("CLIENT_ID", "").strip()
TWILIO_ACCOUNT_SID = _os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _os.getenv("TWILIO_AUTH_TOKEN")
try:
    from plans import get_plan_limits
except ImportError:  # pragma: no cover
    get_plan_limits = None  # type: ignore

router = APIRouter()


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "fable"  # nova, alloy, echo, fable, onyx, shimmer
    speed: Optional[float] = None  # OpenAI 0.25–4.0; if omitted uses business config


@router.post("/api/text-to-speech")
def text_to_speech(
    request: TTSRequest, _: None = Depends(deps.require_active_subscription)
):
    """
    Convert text to speech using OpenAI's TTS API.
    Returns audio file as streaming response.
    Available voices: alloy, echo, fable, onyx, nova, shimmer
    """
    try:
        tts_speed = request.speed if request.speed is not None else config_service.get_tts_speed()
        tts_speed = max(0.25, min(4.0, float(tts_speed)))
        # Generate speech using OpenAI TTS HD model for maximum quality
        response = runtime.client.audio.speech.create(
            model="tts-1-hd",  # HD model for smooth, natural, human-like quality
            voice=request.voice,
            input=add_sentence_pauses(request.text),
            speed=tts_speed,
        )

        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)

        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"},
        )

    except Exception as e:
        raise deps._server_error("text-to-speech failed", e)


@router.get("/api/phone/greeting-audio")
def get_greeting_audio(request: Request):
    """Serve greeting audio using the voice selected in Settings. Cached on disk + in memory."""
    from voice.tts_cache import get_cached, put_cached

    client_id = voice_service._get_client_id_from_call(request)
    if not client_id:
        raise HTTPException(status_code=404, detail="Call session not found")
    database.set_request_client_id(client_id)
    call_sid = request.query_params.get("call_sid") or ""
    cache_key = voice_service._greeting_audio_cache_key(client_id)
    cached = get_cached(voice_service.PROJECT_ROOT, "greeting", cache_key)
    info = config_service.get_business_info()
    tenant = voice_service._tenant_for_call_recording()
    preview_payload = voice_service.build_phone_greeting_payload(info, tenant)
    if cached:
        voice_service._log_greeting_debug(
            "greeting_audio_cache_hit",
            preview_payload,
            call_sid=call_sid,
            cache_hit=True,
        )
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=greeting.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(cached)),
            },
        )
    try:
        voice = config_service.get_tts_voice()
        voice_service._log_greeting_debug(
            "greeting_audio_generating",
            preview_payload,
            call_sid=call_sid,
            cache_hit=False,
        )
        data = voice_service._synthesize_tts_clip(
            preview_payload["spoken_text"], voice=voice, speed=config_service.get_tts_speed()
        )
        put_cached(voice_service.PROJECT_ROOT, "greeting", cache_key, data)
        voice_info(
            "greeting_audio_generated",
            client_id_prefix=(client_id or "")[:12],
            voice=voice,
            bytes=len(data),
            call_sid=call_sid or "",
        )
        return Response(
            content=data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=greeting.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(data)),
            },
        )
    except Exception as e:
        print(f"❌ Failed to generate greeting audio: {e}")
        import traceback

        traceback.print_exc()
        try:
            data = voice_service._synthesize_tts_clip(voice_service.TTS_FALLBACK_TEXT, voice="fable", speed=1.0)
            put_cached(voice_service.PROJECT_ROOT, "greeting", cache_key, data)
            return Response(
                content=data,
                media_type="audio/mpeg",
                headers={"Content-Length": str(len(data))},
            )
        except Exception as e2:
            print(f"❌ Fallback greeting audio failed: {e2}")
            raise HTTPException(
                status_code=500, detail=f"Failed to generate greeting: {e}"
            )


@router.get("/api/phone/got-it-audio")
def get_got_it_audio(request: Request):
    """Serve 'Got it, one moment' using the receptionist voice. Cached on disk + in memory."""
    from voice.tts_cache import get_cached, put_cached

    client_id = voice_service._get_client_id_from_call(request)
    if not client_id:
        raise HTTPException(status_code=404, detail="Call session not found")
    database.set_request_client_id(client_id)
    cache_key = voice_service._got_it_cache_key(client_id)
    cached = get_cached(voice_service.PROJECT_ROOT, "got_it", cache_key)
    if cached:
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=got-it.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(cached)),
            },
        )
    try:
        voice = cache_key[2]
        speed = cache_key[3]
        data = voice_service._synthesize_tts_clip(voice_service.GOT_IT_PHRASE, voice=voice, speed=speed)
        put_cached(voice_service.PROJECT_ROOT, "got_it", cache_key, data)
        voice_info(
            "got_it_audio_generated",
            client_id_prefix=(client_id or "")[:12],
            voice=voice,
            bytes=len(data),
        )
        return Response(
            content=data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=got-it.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(data)),
            },
        )
    except Exception as e:
        print(f"❌ Failed to generate 'got it' audio: {e}")
        import traceback

        traceback.print_exc()
        try:
            data = voice_service._synthesize_tts_clip(voice_service.TTS_FALLBACK_TEXT, voice="fable", speed=1.0)
            put_cached(voice_service.PROJECT_ROOT, "got_it", cache_key, data)
            return Response(
                content=data,
                media_type="audio/mpeg",
                headers={"Content-Length": str(len(data))},
            )
        except Exception as e2:
            print(f"❌ Fallback 'got it' audio failed: {e2}")
            raise HTTPException(
                status_code=500, detail=f"Failed to generate 'got it' audio: {e}"
            )


@router.get("/api/phone/one-moment-audio")
def get_one_moment_audio(request: Request):
    """Serve 'One moment.' from cache for pending-response filler polling."""
    from voice.tts_cache import get_cached, put_cached

    client_id = voice_service._get_client_id_from_call(request)
    if not client_id:
        raise HTTPException(status_code=404, detail="Call session not found")
    database.set_request_client_id(client_id)
    cache_key = voice_service._one_moment_cache_key(client_id)
    cached = get_cached(voice_service.PROJECT_ROOT, "one_moment", cache_key)
    if cached:
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=one-moment.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(cached)),
            },
        )
    try:
        voice = cache_key[2]
        speed = cache_key[3]
        data = voice_service._synthesize_tts_clip(voice_service.ONE_MOMENT_PHRASE, voice=voice, speed=speed)
        put_cached(voice_service.PROJECT_ROOT, "one_moment", cache_key, data)
        voice_info(
            "one_moment_audio_generated",
            client_id_prefix=(client_id or "")[:12],
            voice=voice,
            bytes=len(data),
        )
        return Response(
            content=data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=one-moment.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(data)),
            },
        )
    except Exception as e:
        logger.exception("one_moment_audio_generate_failed: %s", e)
        try:
            data = voice_service._synthesize_tts_clip(voice_service.TTS_FALLBACK_TEXT, voice="fable", speed=1.0)
            put_cached(voice_service.PROJECT_ROOT, "one_moment", cache_key, data)
            return Response(
                content=data,
                media_type="audio/mpeg",
                headers={"Content-Length": str(len(data))},
            )
        except Exception as e2:
            logger.exception("one_moment_audio_fallback_failed: %s", e2)
            raise HTTPException(
                status_code=500, detail=f"Failed to generate 'one moment' audio: {e}"
            )


@router.get("/api/phone/tts-audio-hd")
def get_tts_audio_hd_for_phone(text: str, voice: str = "fable"):
    """
    Generate HD TTS audio for Twilio phone calls (ultra-smooth, no choppiness).
    Used specifically for the initial greeting to ensure perfect quality.
    """
    try:
        # Use tts-1-hd for ultra-smooth, natural speech (no choppiness)
        response = runtime.client.audio.speech.create(
            model="tts-1-hd",  # HD model for ultra-smooth, natural speech
            voice=voice,
            input=add_sentence_pauses(text),
            speed=config_service.get_tts_speed(),
        )

        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)

        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Cache-Control": "no-cache",
            },
        )
    except Exception as e:
        raise deps._server_error("HD TTS generation failed", e)


@router.get("/api/phone/tts-audio")
def get_tts_audio_for_phone(text: str, voice: str = "fable"):
    """
    Generate TTS audio for phone calls.
    This endpoint is called by Twilio to play OpenAI TTS audio.
    """
    try:
        # Use tts-1 for faster generation while maintaining quality
        # tts-1 is faster than tts-1-hd but still sounds natural and smooth
        response = runtime.client.audio.speech.create(
            model="tts-1",  # Faster generation, still high quality
            voice=voice,
            input=add_sentence_pauses(text),
            speed=config_service.get_tts_speed(),
        )

        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)

        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Cache-Control": "no-cache",
            },
        )

    except Exception as e:
        print(f"TTS audio generation error: {e}")
        try:
            response = runtime.client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=add_sentence_pauses(voice_service.TTS_FALLBACK_TEXT),
                speed=1.0,
            )
            audio_bytes = io.BytesIO(response.content)
            audio_bytes.seek(0)
            return StreamingResponse(
                audio_bytes,
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "inline; filename=speech.mp3",
                    "Cache-Control": "no-cache",
                },
            )
        except Exception as e2:
            raise deps._server_error("TTS fallback also failed", e2)


# ===== phone call-flow routes (incoming / speech / recording / status) =====


@router.post("/api/phone/incoming")
async def handle_incoming_call(request: Request):
    if not TWILIO_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Twilio not installed. Install with: pip install twilio",
        )
    """
    Twilio webhook for incoming phone calls.
    This endpoint is called when someone calls your Twilio phone number.
    """
    try:
        voice_info(
            "incoming_call_webhook",
            remote_ip=request.client.host if request.client else "unknown",
            request_id=getattr(request.state, "request_id", None),
        )
        form_data = await request.form()
        form_dict = dict(form_data)
        if not deps._validate_twilio_webhook(request, form_dict):
            auth_warning(
                "voice_webhook_invalid_signature",
                path=request.url.path,
                request_id=getattr(request.state, "request_id", None),
            )
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
        call_sid = form_data.get("CallSid")
        from_number = form_data.get("From")
        to_number = form_data.get("To")

        voice_info(
            "incoming_call",
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
        )

        # Multi-tenant: resolve tenant strictly by Twilio destination number.
        tenant = database.db_tenant_get_by_phone(to_number or "") if runtime.USE_DB else None
        tenant_for_access = tenant
        if tenant:
            database.set_request_client_id(tenant["client_id"])
            if (tenant.get("twilio_phone_number") or "").strip() == (
                to_number or ""
            ).strip():
                voice_info(
                    "tenant_resolved_by_to_number",
                    client_id=tenant["client_id"],
                    tenant_name=tenant.get("name") or "",
                    to_number=to_number,
                )
        else:
            voice_info("tenant_not_resolved", to_number=to_number)
        from webhook_responses import (
            check_webhook_tenant_access,
            subscription_denied_voice_twiml,
        )

        if not check_webhook_tenant_access(
            tenant_for_access,
            channel="voice",
            request_id=getattr(request.state, "request_id", None),
        ):
            return Response(
                content=subscription_denied_voice_twiml(),
                media_type="application/xml",
            )

        # Pre-call usage check: allow overage, log for billing (Option B)
        if runtime.USE_DB and tenant and get_plan_limits:
            limits = get_plan_limits(tenant)
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            usage = database.db_usage_get(tenant["client_id"], month)
            total = (usage.get("voice_minutes") or 0) + (usage.get("sms_count") or 0)
            if total >= limits.get("minutes_cap", 999999):
                deps.audit_log(
                    "usage",
                    "overage_exceeded",
                    client_id=tenant["client_id"],
                    details={
                        "month": month,
                        "total": total,
                        "cap": limits.get("minutes_cap"),
                    },
                    request=request,
                )

        # Pro: call log start + customer memory for repeat callers
        voice_service.call_log_start(call_sid, from_number, to_number)
        client_id = (tenant or {}).get("client_id") or ""
        if not client_id:
            if runtime.USE_DB:
                raise HTTPException(
                    status_code=403, detail="Unknown destination number"
                )
            client_id = CLIENT_ID or "default"
        caller_memory = refresh_caller_memory_for_prompt(from_number, client_id)

        # Create a new session for this call (store client_id for downstream handlers)
        session_id = f"phone-{call_sid}"
        database.set_request_client_id(client_id)
        greeting_plan = voice_service.build_phone_greeting_payload(
            config_service.get_business_info(), tenant_for_access
        )
        voice_service._log_greeting_debug(
            "incoming_call_greeting_plan", greeting_plan, call_sid=call_sid or ""
        )
        voice_info(
            "incoming_call_greeting",
            call_sid=call_sid or "",
            client_id=client_id,
            config_source=greeting_plan.get("config_source"),
            spoken_preview=(greeting_plan.get("spoken_text") or "")[:500],
            voice=greeting_plan.get("voice"),
        )
        voice_info(
            "call_session_started",
            call_sid=call_sid,
            client_id=client_id,
            from_number=from_number,
            to_number=to_number,
        )

        base_url = deps._twilio_base_url(request)
        if not base_url:
            logger.error(
                "[VOICE] incoming_call missing public base URL; set PUBLIC_BASE_URL (or NGROK_URL), "
                "or ensure the reverse proxy forwards Host and X-Forwarded-Proto."
            )
            voice_info("incoming_call_missing_public_base_url", call_sid=call_sid)
            fail_twiml = VoiceResponse()
            fail_twiml.say(
                "Sorry, this phone line is not fully configured yet. Please try again later.",
                voice="alice",
            )
            fail_twiml.hangup()
            return Response(content=str(fail_twiml), media_type="application/xml")

        runtime.call_store.sessions[call_sid] = {
            "session_id": session_id,
            "from_number": from_number,
            "to_number": to_number,
            "client_id": client_id,
            "conversation_history": [],
            "detected_language": "English",
            "started_at": datetime.now().isoformat(),
            "caller_memory": caller_memory,
            "twilio_public_base_url": base_url,
        }
        biz_info = config_service.get_business_info()
        if config_service.staff_roster_ready_for_booking(biz_info):
            svc_n = len(config_service._normalize_service_entries(biz_info.get("services") or []))
            staff_n = len(
                [
                    s
                    for s in (biz_info.get("staff") or [])
                    if (s.get("name") or "").strip()
                ]
            )
            if staff_n >= 2 and svc_n == 0:
                voice_info(
                    "booking_config_incomplete",
                    call_sid=call_sid or "",
                    client_id=client_id,
                    reason="no_services_multi_staff",
                    staff_count=staff_n,
                )
        if not config_service.voice_receptionist_ready(biz_info):
            voice_forward(
                "setup_not_ready_forward",
                call_sid=call_sid or "",
                client_id=client_id,
                forward_kind=(
                    "store_forwarding"
                    if voice_service.setup_transfers_to_store_after_message(biz_info)
                    else "none"
                ),
                roster_ready=config_service.staff_roster_ready_for_booking(biz_info),
                store_phone_ready=config_service.forwarding_phone_ready(biz_info),
                roster_only_gap=voice_service.setup_transfers_to_store_after_message(biz_info),
            )
            setup_twiml = voice_service.twiml_setup_not_ready_handoff(
                base_url, biz_info, call_sid=call_sid or ""
            )
            return Response(content=str(setup_twiml), media_type="application/xml")

        if client_id:
            try:
                await asyncio.to_thread(voice_service._ensure_greeting_audio_cached, client_id)
            except Exception as e:
                voice_warning(
                    "greeting_cache_ensure_failed",
                    call_sid=call_sid or "",
                    client_id_prefix=client_id[:12],
                    error_type=type(e).__name__,
                )
                logger.warning(
                    "ensure greeting cache failed call_sid=%s client_id=%s: %s",
                    call_sid,
                    client_id,
                    e,
                    exc_info=True,
                )
            deps.create_tracked_task(
                voice_service._warm_auxiliary_voice_cache_async(client_id),
                name=f"warm_voice_cache_aux:{client_id}",
            )

        # Create TwiML response
        response = VoiceResponse()

        if (
            TWILIO_AVAILABLE
            and VoiceResponse
            and voice_service._call_recording_enabled_for_tenant(tenant_for_access)
        ):
            cb = f"{base_url.rstrip('/')}/api/phone/recording-complete"
            start = response.start()
            start.recording(
                channels="dual",
                recording_status_callback=cb,
                recording_status_callback_method="POST",
            )

        # Greeting audio uses voice from Settings; pass call_sid so we resolve client_id
        greeting_audio_url = f"{base_url}/api/phone/greeting-audio?call_sid={call_sid}"

        from voice.stt_config import deepgram_env_block_reason, voice_stt_provider

        use_deepgram_stt = voice_service._voice_stt_use_deepgram()
        voice_info(
            "incoming_call_stt_provider",
            provider="deepgram" if use_deepgram_stt else "twilio",
            call_sid=call_sid,
        )
        if voice_stt_provider() == "deepgram" and not use_deepgram_stt:
            env_r = deepgram_env_block_reason()
            if env_r:
                voice_info(
                    "deepgram_requested_but_disabled", reason=env_r, call_sid=call_sid
                )
            else:
                voice_info(
                    "deepgram_requested_but_disabled",
                    reason="twilio_client_unavailable_or_twilio_not_installed",
                    call_sid=call_sid,
                )

        voice_call_phase(
            "incoming_greeting",
            call_sid=call_sid or "",
            client_id=client_id,
            stt="deepgram" if use_deepgram_stt else "twilio",
        )

        if use_deepgram_stt:
            from voice.twiml_stt import (
                append_connect_stream,
                append_deepgram_silence_followup_after_stream,
                next_media_stream_generation,
            )

            response.play(greeting_audio_url)
            gen = next_media_stream_generation(call_sid, runtime.call_store.sessions[call_sid])
            append_connect_stream(
                response,
                call_sid=call_sid,
                base_url=base_url,
                stream_generation=gen,
            )
            still_there_url = (
                f"{base_url}/api/phone/tts-audio?text={quote('Still there?')}"
                f"&voice={config_service.get_tts_voice()}"
            )
            append_deepgram_silence_followup_after_stream(
                response,
                call_sid=call_sid,
                base_url=base_url,
                still_there_play_url=still_there_url,
                call_state=runtime.call_store.sessions[call_sid],
            )
            voice_service._persist_call_session(call_sid)
            voice_debug(
                "incoming_deepgram_twiml_ready",
                call_sid=call_sid,
                media_stream_gen=runtime.call_store.get_media_stream_max_gen(call_sid),
                has_public_base_url=bool(
                    (runtime.call_store.get(call_sid) or {}).get("twilio_public_base_url")
                ),
            )
            return Response(content=str(response), media_type="application/xml")

        from voice.twiml_stt import append_gather_listen

        append_gather_listen(
            response,
            base_url,
            language="en-US",
            nested_play_url=greeting_audio_url,
        )

        return Response(content=str(response), media_type="application/xml")

    except HTTPException:
        # Intentional HTTP responses (e.g. 403 invalid-signature) must propagate —
        # the catch-all below would otherwise swallow them into a 200 fallback TwiML,
        # defeating the webhook signature gate.
        raise
    except Exception as e:
        voice_warning(
            "incoming_call_failed",
            error_type=type(e).__name__,
        )
        logger.exception("incoming_call_failed")
        response = VoiceResponse()
        base_url = deps._twilio_base_url(request)

        # On error, forward to business phone if available
        forwarding_phone = config_service.get_business_info().get("forwarding_phone")
        if forwarding_phone:
            voice_forward(
                "incoming_error_forward",
                call_sid=str(form_data.get("CallSid") if "form_data" in dir() else ""),
                forward_kind="fallback",
                has_fallback_configured=True,
                error_type=type(e).__name__,
            )
            error_text = "I'm experiencing technical difficulties. Let me connect you with someone who can help."
            error_encoded = quote(error_text)
            tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={config_service.get_tts_voice()}"
            response.play(tts_audio_url)
            response = voice_service.forward_call_to_business(forwarding_phone, base_url, "English")
            return Response(content=str(response), media_type="application/xml")
        else:
            # Fallback: just say error message if no forwarding number
            error_text = (
                "I'm sorry, I'm having technical difficulties. Please try again later."
            )
            error_encoded = quote(error_text)
            tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={config_service.get_tts_voice()}"
            response.play(tts_audio_url)
            response.hangup()
            return Response(content=str(response), media_type="application/xml")


@router.post("/api/phone/recording-complete")
async def handle_recording_complete(request: Request):
    """Twilio recording status callback for full-call dual-channel recording."""
    if not TWILIO_AVAILABLE:
        return Response(content="", status_code=200, media_type="text/plain")
    try:
        form_data = await request.form()
        form_dict = dict(form_data)
        if not deps._validate_twilio_webhook(request, form_dict):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = (form_data.get("CallSid") or "").strip()
        recording_sid = (form_data.get("RecordingSid") or "").strip() or None
        recording_url = (form_data.get("RecordingUrl") or "").strip() or None
        recording_status = (form_data.get("RecordingStatus") or "").strip() or None
        dur_raw = (form_data.get("RecordingDuration") or "").strip()
        duration_sec: Optional[int] = None
        if dur_raw:
            try:
                duration_sec = int(float(dur_raw))
            except (TypeError, ValueError):
                pass

        client_id: Optional[str] = None
        if call_sid and call_sid in runtime.call_store.sessions:
            client_id = runtime.call_store.sessions[call_sid].get("client_id")
        if not client_id and runtime.USE_DB:
            client_id = database.db_call_log_get_client_id_by_call_sid(call_sid)
        if not client_id:
            voice_warning(
                "recording_complete_unresolved_call_sid", call_sid=call_sid or ""
            )
            return Response(content="", status_code=200, media_type="text/plain")
        database.set_request_client_id(client_id)

        tenant_rec = (
            database.db_tenant_get_by_client_id(client_id) if runtime.USE_DB and client_id else None
        )
        if not voice_service._call_recording_enabled_for_tenant(tenant_rec):
            voice_info(
                "recording_complete_ignored_plan",
                call_sid=call_sid or "",
                client_id_prefix=(client_id or "")[:12],
            )
            return Response(content="OK", status_code=200, media_type="text/plain")

        if runtime.USE_DB:
            database.db_call_log_update_recording(
                call_sid,
                client_id,
                recording_sid=recording_sid,
                recording_url=recording_url,
                recording_duration_sec=duration_sec,
                recording_status=recording_status,
            )
        voice_service.call_log_merge_recording(
            call_sid,
            recording_sid=recording_sid,
            recording_url=recording_url,
            recording_duration_sec=duration_sec,
            recording_status=recording_status,
        )
        if not runtime.USE_DB:
            voice_service._file_call_log_merge_recording(
                call_sid,
                recording_sid=recording_sid,
                recording_url=recording_url,
                recording_duration_sec=duration_sec,
                recording_status=recording_status,
            )

        st = (recording_status or "").lower()
        if (
            st == "completed"
            and recording_url
            and voice_service._call_summary_enabled_for_tenant(tenant_rec)
        ):
            deps.create_tracked_task(
                voice_service._schedule_recording_summary(
                    call_sid, client_id, recording_url, duration_sec
                ),
                name=f"recording_summary:{call_sid}",
            )
        return Response(content="", status_code=200, media_type="text/plain")
    except Exception as e:
        logger.exception("recording-complete webhook error: %s", e)
        return Response(content="", status_code=200, media_type="text/plain")


@router.post("/api/phone/process-speech")
async def process_speech(request: Request):
    if not TWILIO_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Twilio not installed. Install with: pip install twilio",
        )
    """
    Process speech input from phone call and generate AI response.
    """
    try:
        form_data = await request.form()
        if not deps._validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = form_data.get("CallSid")
        speech_result = form_data.get("SpeechResult", "")
        confidence = form_data.get("Confidence", "0")

        voice_info(
            "speech_received",
            call_sid=call_sid or "",
            transcript_len=len(speech_result or ""),
            confidence=confidence,
        )

        voice_service._restore_call_context(call_sid or "")
        base_url = deps._twilio_base_url(request)

        from voice.utterance import apply_caller_utterance

        outcome = await apply_caller_utterance(
            call_sid or "",
            speech_result or "",
            float(confidence or 0),
            base_url,
        )
        if outcome.mode == "replace_call_twiml" and outcome.replacement_twiml:
            return Response(
                content=outcome.replacement_twiml, media_type="application/xml"
            )

        response = VoiceResponse()
        got_it_audio_url = f"{base_url}/api/phone/got-it-audio?call_sid={call_sid}"
        response.play(got_it_audio_url)
        response.redirect(
            f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
        )

        return Response(content=str(response), media_type="application/xml")

    except Exception as e:
        voice_warning(
            "process_speech_failed",
            call_sid=str(call_sid if "call_sid" in dir() else ""),
            error_type=type(e).__name__,
        )
        logger.exception("process_speech_failed")

        # On error, offer to forward to a real person
        response = VoiceResponse()
        base_url = deps._twilio_base_url(request)

        # Check if we have a forwarding number - if so, forward on error
        forwarding_phone = config_service.get_business_info().get("forwarding_phone")
        if forwarding_phone:
            voice_forward(
                "process_speech_error_forward",
                call_sid=str(call_sid if "call_sid" in dir() else ""),
                forward_kind="fallback",
                has_fallback_configured=True,
                error_type=type(e).__name__,
            )
            error_text = "I'm experiencing technical difficulties. Let me connect you with someone who can help."
            error_encoded = quote(error_text)
            tts_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={config_service.get_tts_voice()}"
            response.play(tts_url)
            response = voice_service.forward_call_to_business(forwarding_phone, base_url, "English")
            return Response(content=str(response), media_type="application/xml")
        else:
            # Avoid redirect-only loops on errors: prompt once inside Gather, then end the call.
            error_text = "I'm sorry, I didn't catch that. Could you repeat?"
            error_encoded = quote(error_text)
            tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={config_service.get_tts_voice()}"
            response.play(tts_audio_url)
            gather = response.gather(
                input="speech",
                action=f"{base_url}/api/phone/process-speech",
                method="POST",
                speech_timeout="auto",
                timeout=10,
            )
            gather.say("Please speak after the tone.", voice="alice")
            response.say("We're having trouble on this line. Goodbye.", voice="alice")
            response.hangup()
            return Response(content=str(response), media_type="application/xml")


@router.post("/api/phone/status")
async def handle_call_status(request: Request):
    """
    Twilio webhook for call status updates (call ended, etc.)
    """
    try:
        form_data = await request.form()
        if not deps._validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")

        voice_call_phase(
            "call_status",
            call_sid=call_sid or "",
            status=call_status or "",
        )
        voice_service._restore_call_context(call_sid or "")

        # Clean up when call ends + Pro: persist call log and customer memory
        if call_status in ["completed", "failed", "busy", "no-answer", "canceled"]:
            # Read Twilio Duration and set in voice_service.call_log_entries before voice_service.call_log_end
            duration_raw = form_data.get("Duration")
            if duration_raw is not None:
                try:
                    dur = int(duration_raw)
                    if call_sid in voice_service.call_log_entries and dur >= 0:
                        voice_service.call_log_entries[call_sid]["duration_sec"] = dur
                except (ValueError, TypeError):
                    pass
            # Capture client_id, from_number, appointment_created, duration_sec before we delete from runtime.call_store.sessions
            client_id_before = None
            from_number_before = None
            appointment_created = False
            if call_sid in runtime.call_store.sessions:
                call_data_cp = runtime.call_store.sessions[call_sid]
                client_id_before = call_data_cp.get("client_id")
                from_number_before = call_data_cp.get("from_number")
                appointment_created = call_data_cp.get("appointment_created") or False
            if not client_id_before and runtime.USE_DB and call_sid in voice_service.call_log_entries:
                client_id_before = voice_service.call_log_entries[call_sid].get("client_id")
            if not from_number_before and call_sid in voice_service.call_log_entries:
                from_number_before = voice_service.call_log_entries[call_sid].get("from_number")
            duration_sec = 0
            if call_sid in voice_service.call_log_entries:
                duration_sec = voice_service.call_log_entries[call_sid].get("duration_sec") or 0
            if call_sid in runtime.call_store.sessions:
                call_data = runtime.call_store.sessions[call_sid]
                outcome = call_data.get("outcome")
                if not outcome and appointment_created:
                    outcome = "answered_by_ai"
                    call_data["outcome"] = outcome
                elif (
                    not outcome
                    and call_data.get("booking_intent")
                    and not appointment_created
                ):
                    outcome = "no_booking"
                    call_data["outcome"] = outcome
                if outcome:
                    voice_service.call_log_set_outcome(call_sid, outcome)
                from_number = call_data.get("from_number")
                if from_number:
                    update_caller_memory(from_number)
                voice_service.call_log_end(call_sid)
                voice_service.cleanup_call_runtime_state(call_sid or "")
                voice_call_phase(
                    "call_session_cleaned",
                    call_sid=call_sid or "",
                    client_id=str(client_id_before or ""),
                    outcome=outcome or "",
                    duration_sec=duration_sec,
                )
            elif call_sid in voice_service.call_log_entries:
                # Call was logged but not in runtime.call_store.sessions (e.g. quick hangup)
                voice_service.call_log_set_outcome(
                    call_sid, "missed" if call_status == "completed" else call_status
                )
                voice_service.call_log_end(call_sid)
                voice_service.cleanup_call_runtime_state(call_sid or "")
            # Lead capture: when call ended without booking and plan allows
            if (
                runtime.USE_DB
                and client_id_before
                and client_id_before != "default"
                and from_number_before
                and get_plan_limits
            ):
                try:
                    tenant = database.db_tenant_get_by_client_id(client_id_before)
                    if (
                        tenant
                        and get_plan_limits(tenant).get("has_lead_capture")
                        and not appointment_created
                    ):
                        database.db_leads_insert(
                            client_id_before,
                            None,
                            from_number_before,
                            "inquiry",
                            "call",
                        )
                except Exception as e:
                    logger.error(
                        "lead_capture_failed",
                        extra={"client_id": client_id_before, "error": str(e)},
                    )
            # Record voice usage for billing (graceful degradation: log on failure, do not raise)
            if runtime.USE_DB and client_id_before and client_id_before != "default":
                try:
                    minutes = max(0, math.ceil(duration_sec / 60))
                    month = datetime.now(timezone.utc).strftime("%Y-%m")
                    if not database.db_usage_increment_voice(client_id_before, month, minutes):
                        logger.error(
                            "usage_increment_failed",
                            extra={
                                "client_id": client_id_before,
                                "month": month,
                                "error": "database.db_usage_increment_voice returned False",
                            },
                        )
                except Exception as e:
                    logger.error(
                        "usage_increment_failed",
                        extra={"client_id": client_id_before, "error": str(e)},
                    )

        return Response(content="OK", media_type="text/plain")

    except Exception as e:
        voice_warning("call_status_handler_failed", error_type=type(e).__name__)
        logger.exception("call_status_handler_failed")
        return Response(content="OK", media_type="text/plain")


@router.post("/api/phone/no-speech")
async def handle_no_speech(request: Request):
    """
    After listen windows expire with no caller speech: forward to fallback number only here,
    not on every AI turn. Caller must stay silent through Still there? + second listen.
    """
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed")
    try:
        form_data = await request.form()
        if not deps._validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = voice_service._call_sid_from_form(form_data)
        voice_service._restore_call_context(call_sid or "")
        base_url = deps._twilio_base_url(request)
        call_data = runtime.call_store.sessions.get(call_sid, {}) if call_sid else {}
        detected_lang = call_data.get("detected_language") or "English"
        forwarding_phone = (config_service.get_business_info().get("forwarding_phone") or "").strip()

        # Race: caller spoke (Deepgram REST update) while TwiML still had a queued no-speech redirect.
        if call_sid and call_sid in runtime.call_store.response_status:
            st = (runtime.call_store.response_status.get(call_sid) or {}).get("status") or "pending"
            voice_respond_branch(
                "no_speech_skipped_active_turn",
                call_sid=call_sid,
                client_id=str(call_data.get("client_id") or ""),
                status=st,
            )
            response = VoiceResponse()
            response.redirect(
                f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
            )
            return Response(content=str(response), media_type="application/xml")

        # After AI spoke, silence on the follow-up listen is expected — re-prompt once, do not
        # bounce to /respond (runtime.call_store.response_status was cleared when the reply TwiML was returned).
        if call_data.get("awaiting_caller_reply"):
            from voice.twiml_stt import empty_retry_twiml

            runtime.call_store.merge_session(call_sid, {"awaiting_caller_reply": False})
            voice_respond_branch(
                "no_speech_post_ai_reprompt",
                call_sid=call_sid or "",
                client_id=str(call_data.get("client_id") or ""),
                status="reprompt",
            )
            lang_code = voice_service.get_twilio_language_code(detected_lang)
            xml = empty_retry_twiml(
                base_url=base_url,
                language=lang_code,
                use_deepgram=voice_service._voice_stt_use_deepgram(),
                call_sid=call_sid,
                call_state=runtime.call_store.sessions.get(call_sid, {}),
            )
            return Response(content=xml, media_type="application/xml")

        if forwarding_phone:
            voice_forward(
                "no_speech_timeout",
                call_sid=call_sid or "",
                client_id=str(call_data.get("client_id") or ""),
                forward_kind="fallback",
                has_fallback_configured=True,
            )
            if call_sid:
                voice_service._merge_call_session(call_sid, {"outcome": "forwarded"})
            if call_sid:
                voice_service.call_log_set_outcome(call_sid, "forwarded")
            response = voice_service.forward_call_to_business(
                forwarding_phone, base_url, detected_lang
            )
        else:
            voice_respond_branch(
                "no_speech_goodbye",
                call_sid=call_sid or "",
                client_id=str(call_data.get("client_id") or ""),
                status="hangup",
            )
            response = VoiceResponse()
            goodbye_text = "Thanks for calling! Have a wonderful day!"
            goodbye_url = f"{base_url}/api/phone/tts-audio?text={quote(goodbye_text)}&voice={config_service.get_tts_voice()}"
            response.play(goodbye_url)
            response.hangup()
        return Response(content=str(response), media_type="application/xml")
    except Exception as e:
        voice_warning(
            "no_speech_handler_failed",
            call_sid=(form_data.get("CallSid") if "form_data" in dir() else "") or "",
            error_type=type(e).__name__,
        )
        logger.exception("no_speech_handler_failed")
        response = VoiceResponse()
        response.say("Thanks for calling. Goodbye.", voice="alice")
        response.hangup()
        return Response(content=str(response), media_type="application/xml")


@router.post("/api/phone/respond")
async def respond_with_audio(request: Request):
    """
    Polling endpoint that checks if response audio is ready.
    Returns audio when ready, or filler + redirect if still pending.
    """
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed")

    try:
        form_data = await request.form()
        if not deps._validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = voice_service._call_sid_from_form(form_data)
        voice_service._restore_call_context(call_sid or "")
        # base_url needed for voice_service.forward_call_to_business in all branches
        base_url = deps._twilio_base_url(request)
        if not call_sid or call_sid not in runtime.call_store.response_status:
            # GPT still processing or caller has not spoken yet — keep polling; never auto-forward.
            call_data_poll = runtime.call_store.sessions.get(call_sid, {}) if call_sid else {}
            voice_respond_branch(
                "poll_no_status",
                call_sid=call_sid or "",
                client_id=str(call_data_poll.get("client_id") or ""),
                status="pending",
                has_active_call=bool(call_sid and call_sid in runtime.call_store.sessions),
            )
            response = VoiceResponse()
            filler_audio_url = (
                f"{base_url}/api/phone/one-moment-audio?call_sid={call_sid}"
            )
            response.play(filler_audio_url)
            response.pause(length=1)
            response.redirect(
                f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
            )
            return Response(content=str(response), media_type="application/xml")

        status_data = runtime.call_store.response_status[call_sid]
        status = status_data.get("status", "pending")
        response = VoiceResponse()

        if status == "ready":
            call_data = runtime.call_store.sessions.get(call_sid, {})
            voice_respond_branch(
                "play_ai_reply",
                call_sid=call_sid or "",
                client_id=str(call_data.get("client_id") or ""),
                status="ready",
                stt_provider="deepgram" if voice_service._voice_stt_use_deepgram() else "twilio",
            )
            # Audio is ready - play it
            audio_url = status_data.get("audio_url")
            if audio_url:
                response.play(audio_url)
                try:
                    # After playing, set up next input gathering
                    detected_lang = call_data.get("detected_language") or "English"
                    twilio_lang_code = voice_service.get_twilio_language_code(detected_lang)
                    still_there_url = f"{base_url}/api/phone/tts-audio?text={quote('Still there?')}&voice={config_service.get_tts_voice()}"

                    if voice_service.uses_non_latin_script(
                        detected_lang
                    ) and not voice_service._conversation_prefers_english_stt(call_data):
                        response.record(
                            action=f"{base_url}/api/phone/process-recording",
                            method="POST",
                            max_length=15,
                            finish_on_key="#",
                            recording_status_callback=f"{base_url}/api/phone/recording-status",
                        )
                        response.say(
                            "Please speak now, then press pound when done.",
                            language="en-US",
                        )
                    else:
                        from voice.twiml_stt import (
                            append_post_ai_listen_with_still_there,
                        )

                        append_post_ai_listen_with_still_there(
                            response,
                            call_sid=call_sid,
                            base_url=base_url,
                            twilio_lang_code=twilio_lang_code,
                            still_there_play_url=still_there_url,
                            use_deepgram=voice_service._voice_stt_use_deepgram(),
                            call_state=runtime.call_store.sessions.get(call_sid, {}),
                        )
                        if call_sid:
                            runtime.call_store.merge_session(
                                call_sid, {"awaiting_caller_reply": True}
                            )
                except Exception as e:
                    voice_warning(
                        "respond_ready_listen_setup_failed",
                        call_sid=call_sid or "",
                        client_id=str(call_data.get("client_id") or "")[:12],
                        error_type=type(e).__name__,
                        error_detail=str(e)[:200],
                    )
                    response = VoiceResponse()
                    response.hangup()

                # Clean up status
                if call_sid in runtime.call_store.response_status:
                    del runtime.call_store.response_status[call_sid]

                return Response(content=str(response), media_type="application/xml")

        elif status == "forward":
            # Forward to business phone
            forwarding_phone = status_data.get("forwarding_phone")
            if forwarding_phone:
                voice_forward(
                    "respond_status_forward",
                    call_sid=call_sid or "",
                    client_id=str(
                        runtime.call_store.sessions.get(call_sid, {}).get("client_id") or ""
                    ),
                    forward_kind="fallback_or_staff",
                    has_fallback_configured=True,
                )
                detected_lang = runtime.call_store.sessions.get(call_sid, {}).get(
                    "detected_language"
                ) or "English"
                response = voice_service.forward_call_to_business(
                    forwarding_phone, base_url, detected_lang
                )
                # Clean up status
                if call_sid in runtime.call_store.response_status:
                    del runtime.call_store.response_status[call_sid]
                return Response(content=str(response), media_type="application/xml")

        elif status == "error":
            # Error occurred - forward to business phone if available
            forwarding_phone = config_service.get_business_info().get("forwarding_phone")
            if forwarding_phone:
                voice_forward(
                    "respond_status_error_forward",
                    call_sid=call_sid or "",
                    client_id=str(
                        runtime.call_store.sessions.get(call_sid, {}).get("client_id") or ""
                    ),
                    forward_kind="fallback",
                    has_fallback_configured=True,
                )
                detected_lang = runtime.call_store.sessions.get(call_sid, {}).get(
                    "detected_language"
                ) or "English"
                response = voice_service.forward_call_to_business(
                    forwarding_phone, base_url, detected_lang
                )
                # Clean up status
                if call_sid in runtime.call_store.response_status:
                    del runtime.call_store.response_status[call_sid]
                return Response(content=str(response), media_type="application/xml")
            else:
                voice_respond_branch(
                    "error_no_fallback",
                    call_sid=call_sid or "",
                    status="error",
                )
                # Fallback: return error message if no forwarding number
                response.say(
                    "I'm sorry, I'm having technical difficulties. Please try again later.",
                    voice="alice",
                )
                response.hangup()
                # Clean up status
                if call_sid in runtime.call_store.response_status:
                    del runtime.call_store.response_status[call_sid]
                return Response(content=str(response), media_type="application/xml")

        else:
            voice_respond_branch(
                "poll_pending",
                call_sid=call_sid or "",
                client_id=str(runtime.call_store.sessions.get(call_sid, {}).get("client_id") or ""),
                status=status,
            )
            # Still pending - play filler and redirect again
            # Use OpenAI TTS (Fable voice) for consistency
            filler_text = "One sec."
            filler_encoded = quote(filler_text)
            filler_audio_url = f"{base_url}/api/phone/tts-audio?text={filler_encoded}&voice={config_service.get_tts_voice()}"
            response.play(filler_audio_url)
            response.pause(length=1)
            response.redirect(
                f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
            )
            return Response(content=str(response), media_type="application/xml")

    except Exception as e:
        logger.exception("Error in respond endpoint: %s", e)
        import traceback

        traceback.print_exc()
        response = VoiceResponse()
        base_url = deps._twilio_base_url(request)
        # On error, forward to business phone if available
        forwarding_phone = config_service.get_business_info().get("forwarding_phone")
        if forwarding_phone:
            voice_forward(
                "respond_endpoint_exception_forward",
                call_sid=str(call_sid or ""),
                client_id=str(
                    runtime.call_store.sessions.get(call_sid or "", {}).get("client_id") or ""
                ),
                forward_kind="fallback",
                has_fallback_configured=True,
                error_type=type(e).__name__,
            )
            # Try to get call data for language
            call_data = runtime.call_store.sessions.get(call_sid, {})
            detected_lang = call_data.get("detected_language") or "English"
            response = voice_service.forward_call_to_business(
                forwarding_phone, base_url, detected_lang
            )
            # Clean up status
            if call_sid in runtime.call_store.response_status:
                del runtime.call_store.response_status[call_sid]
            return Response(content=str(response), media_type="application/xml")
        else:
            voice_respond_branch(
                "respond_endpoint_exception",
                call_sid=str(call_sid or ""),
                status="error",
                error_type=type(e).__name__,
            )
            # Fallback: return error message if no forwarding number
            response.say(
                "I'm sorry, I'm having technical difficulties. Please try again later.",
                voice="alice",
            )
            response.hangup()
            return Response(content=str(response), media_type="application/xml")


@router.post("/api/phone/process-recording")
async def process_recording(request: Request):
    """
    Process audio recording from Twilio for languages with non-Latin scripts.
    Transcribes using Whisper for better accuracy.
    """
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed")

    try:
        form_data = await request.form()
        if not deps._validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = voice_service._call_sid_from_form(form_data)
        recording_url = form_data.get("RecordingUrl", "")
        voice_service._restore_call_context(call_sid or "")

        logger.info("recording_received call_sid=%s", call_sid or "")

        if not call_sid or call_sid not in runtime.call_store.sessions:
            response = VoiceResponse()
            response.say(
                "I'm sorry, I lost track of our conversation. Please call back.",
                voice="alice",
            )
            return Response(content=str(response), media_type="application/xml")

        if not recording_url:
            logger.warning("recording_missing_url call_sid=%s", call_sid or "")
            response = VoiceResponse()
            response.say(
                "I didn't receive the recording. Please try again.", voice="alice"
            )
            bu = deps._twilio_base_url(request)
            if bu:
                response.redirect(f"{bu}/api/phone/process-speech", method="POST")
            return Response(content=str(response), media_type="application/xml")

        if not voice_service._is_trusted_twilio_media_url(recording_url):
            logger.warning("recording_url_untrusted_host call_sid=%s", call_sid or "")
            response = VoiceResponse()
            response.say(
                "I had trouble processing the recording. Please try again.",
                voice="alice",
            )
            bu = deps._twilio_base_url(request)
            if bu:
                response.redirect(f"{bu}/api/phone/process-speech", method="POST")
            return Response(content=str(response), media_type="application/xml")

        call_data = runtime.call_store.sessions.get(call_sid, {})

        # Download the recording from Twilio using httpx
        # httpx is already available in the environment
        try:
            import httpx
        except ImportError:
            # Fallback if httpx not available (shouldn't happen)
            raise HTTPException(status_code=500, detail="httpx library not available")

        recording_response = httpx.get(
            recording_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=30.0
        )
        if recording_response.status_code != 200:
            logger.warning(
                "recording_download_failed call_sid=%s status=%s",
                call_sid or "",
                recording_response.status_code,
            )
            response = VoiceResponse()
            response.say(
                "I had trouble processing the recording. Please try again.",
                voice="alice",
            )
            bu = deps._twilio_base_url(request)
            if bu:
                response.redirect(f"{bu}/api/phone/process-speech", method="POST")
            return Response(content=str(response), media_type="application/xml")

        # Transcribe with Whisper
        audio_data = recording_response.content
        temp_file = io.BytesIO(audio_data)
        temp_file.name = "recording.wav"

        logger.info("recording_transcribe_start call_sid=%s", call_sid or "")
        transcript = runtime.client.audio.transcriptions.create(
            model="whisper-1",
            file=temp_file,
            # language parameter omitted to allow auto-detection
        )

        speech_result = transcript.text
        logger.info(
            "recording_transcribe_ok call_sid=%s transcript_len=%s",
            call_sid or "",
            len(speech_result or ""),
        )

        base_url = deps._twilio_base_url(request)
        rec_key = (form_data.get("RecordingSid") or recording_url or "").strip()
        if rec_key and call_data.get("_last_processed_recording") == rec_key:
            voice_info("process_recording_duplicate_skipped", call_sid=call_sid or "")
            response = VoiceResponse()
            response.redirect(
                f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
            )
            return Response(content=str(response), media_type="application/xml")
        if rec_key:
            rec_updates: dict[str, Any] = {"_last_processed_recording": rec_key}
            if voice_service._text_looks_latin(speech_result):
                rec_updates["detected_language"] = "English"
            voice_service._merge_call_session(call_sid, rec_updates)

        from voice.utterance import apply_caller_utterance

        outcome = await apply_caller_utterance(
            call_sid or "",
            speech_result or "",
            0.9,
            base_url,
        )
        if outcome.mode == "replace_call_twiml" and outcome.replacement_twiml:
            return Response(
                content=outcome.replacement_twiml, media_type="application/xml"
            )

        response = VoiceResponse()
        response.play(f"{base_url}/api/phone/got-it-audio?call_sid={call_sid}")
        response.redirect(
            f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
        )
        return Response(content=str(response), media_type="application/xml")

    except Exception as e:
        voice_warning(
            "process_recording_failed",
            call_sid=str(call_sid if "call_sid" in dir() else ""),
            error_type=type(e).__name__,
        )
        logger.exception("process_recording_failed")
        response = VoiceResponse()
        base_url = deps._twilio_base_url(request)

        # On error, forward to business phone if available
        forwarding_phone = config_service.get_business_info().get("forwarding_phone")
        if forwarding_phone:
            voice_forward(
                "process_recording_error_forward",
                call_sid=str(call_sid if "call_sid" in dir() else ""),
                forward_kind="fallback",
                has_fallback_configured=True,
                error_type=type(e).__name__,
            )
            # Try to get call data for language
            call_data = runtime.call_store.sessions.get(call_sid, {})
            detected_lang = call_data.get("detected_language") or "English"
            response = voice_service.forward_call_to_business(
                forwarding_phone, base_url, detected_lang
            )
            return Response(content=str(response), media_type="application/xml")
        else:
            # Fallback: ask to try again if no forwarding number
            response.say(
                "I'm sorry, I had trouble processing that. Please try again.",
                voice="alice",
            )
            response.redirect(f"{base_url}/api/phone/process-speech", method="POST")
            return Response(content=str(response), media_type="application/xml")


@router.post("/api/phone/recording-status")
async def recording_status(request: Request):
    """Handle recording status updates from Twilio"""
    # This endpoint can be used for logging or additional processing
    form_data = await request.form()
    if not deps._validate_twilio_webhook(request, dict(form_data)):
        return Response(content="Forbidden", status_code=403, media_type="text/plain")
    logger.info("recording_status_update status=%s", form_data.get("RecordingStatus"))
    return Response(content="OK", media_type="text/plain")


@router.post("/api/phone/transcribe")
def transcribe_phone_audio(request: Request, audio_data: str = Form(...)):
    """
    Transcribe audio from phone call using OpenAI Whisper.
    This endpoint receives base64-encoded audio from Twilio.
    """
    try:
        if not deps._validate_twilio_webhook(request, {"audio_data": audio_data}):
            raise HTTPException(status_code=403, detail="Forbidden")
        # Decode base64 audio
        audio_bytes = base64.b64decode(audio_data)

        # Save to temporary file
        temp_file = io.BytesIO(audio_bytes)
        temp_file.name = "audio.webm"

        # Transcribe using OpenAI Whisper - auto-detect language for multi-language support
        transcript = runtime.client.audio.transcriptions.create(
            model="whisper-1",
            file=temp_file,
            # language parameter omitted to allow auto-detection of any language
        )

        return {"transcript": transcript.text}

    except Exception as e:
        raise deps._server_error("transcription failed", e)


@router.get("/api/phone/calls")
def get_active_calls(_: str = Depends(deps.require_admin)):
    """Admin-only: list in-flight voice sessions (PII — never public)."""
    return {
        "active_calls": len(runtime.call_store.sessions),
        "calls": [
            {
                "call_sid": sid,
                "from": call_data["from_number"],
                "to": call_data["to_number"],
                "started_at": call_data["started_at"],
            }
            for sid, call_data in runtime.call_store.sessions.items()
        ],
    }


# ===== Twilio Media Streams websocket =====


@router.websocket("/api/phone/media")
async def phone_media_websocket(websocket: WebSocket):
    """Twilio Media Streams → Deepgram Nova-2 live STT (when VOICE_STT_PROVIDER=deepgram)."""
    if not TWILIO_AVAILABLE or not runtime.twilio_client:
        await websocket.close(code=1011)
        return
    from voice.media_ws import handle_phone_media_websocket

    await handle_phone_media_websocket(websocket, runtime.twilio_client)


@router.post("/api/phone/stream")
def handle_media_stream(request: Request):
    """
    Legacy placeholder. Real-time media uses WebSocket ``GET /api/phone/media`` (Twilio Media Streams).
    """
    return {
        "message": "Use WebSocket wss://…/api/phone/media for Twilio Media Streams (VOICE_STT_PROVIDER=deepgram).",
        "websocket_path": "/api/phone/media",
    }
