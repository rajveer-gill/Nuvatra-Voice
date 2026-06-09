"""Phone/voice routes — audio (TTS) endpoints.

Twilio fetches these for greeting/got-it/one-moment/arbitrary TTS clips. All voice helpers
now live in voice_service / config_service / deps; this router is a thin transport layer.
"""

from __future__ import annotations

import io
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config_service
import database
import deps
import runtime
import voice_service
from observability import voice_info
from voice_preview import add_sentence_pauses

router = APIRouter()


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "fable"  # nova, alloy, echo, fable, onyx, shimmer
    speed: Optional[float] = None  # OpenAI 0.25–4.0; if omitted uses business config


@router.post("/api/text-to-speech")
async def text_to_speech(
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
async def get_greeting_audio(request: Request):
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
            data = voice_service._synthesize_tts_clip(TTS_FALLBACK_TEXT, voice="fable", speed=1.0)
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
async def get_got_it_audio(request: Request):
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
            data = voice_service._synthesize_tts_clip(TTS_FALLBACK_TEXT, voice="fable", speed=1.0)
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
async def get_one_moment_audio(request: Request):
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
            data = voice_service._synthesize_tts_clip(TTS_FALLBACK_TEXT, voice="fable", speed=1.0)
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
async def get_tts_audio_hd_for_phone(text: str, voice: str = "fable"):
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
async def get_tts_audio_for_phone(text: str, voice: str = "fable"):
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
                input=add_sentence_pauses(TTS_FALLBACK_TEXT),
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
