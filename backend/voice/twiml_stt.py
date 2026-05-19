"""
TwiML builders for voice STT: Deepgram (Media Streams) or Twilio Gather fallback.

All listen turns should go through these helpers so VOICE_STT_PROVIDER=deepgram applies
to every conversational turn, not only the first inbound greeting.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

from voice.media_token import mint_media_stream_token
from voice.stt_config import http_to_ws_base

try:
    from twilio.twiml.voice_response import Connect, Stream, VoiceResponse

    _TWILIO_OK = True
except ImportError:
    Connect = None  # type: ignore[misc, assignment]
    Stream = None  # type: ignore[misc, assignment]
    VoiceResponse = None  # type: ignore[misc, assignment]
    _TWILIO_OK = False

GATHER_HINTS = "appointment, schedule, message, hours, contact, help"
PROCESS_SPEECH_PATH = "/api/phone/process-speech"


def next_media_stream_generation(call_state: dict[str, Any]) -> int:
    """Monotonic generation per call; bound into stream tokens to block replay."""
    g = int(call_state.get("media_stream_gen") or 0) + 1
    call_state["media_stream_gen"] = g
    return g


def append_connect_stream(
    response: Any,
    *,
    call_sid: str,
    base_url: str,
    stream_generation: int,
) -> None:
    """Append <Connect><Stream> with signed token (includes stream generation)."""
    if not _TWILIO_OK or Connect is None or Stream is None:
        return
    bu = base_url.rstrip("/")
    wss_base = http_to_ws_base(bu)
    stream_url = f"{wss_base}/api/phone/media"
    token = mint_media_stream_token(call_sid, stream_generation=stream_generation)
    connect = Connect()
    stream = Stream(url=stream_url)
    if token:
        stream.parameter(name="token", value=token)
    connect.append(stream)
    response.append(connect)


def got_it_respond_twiml(call_sid: str, base_url: str) -> str:
    """TwiML after a successful utterance: filler audio then poll for AI response."""
    if not _TWILIO_OK or VoiceResponse is None:
        return '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
    bu = base_url.rstrip("/")
    vr = VoiceResponse()
    got_it_url = f"{bu}/api/phone/got-it-audio?call_sid={call_sid}"
    vr.play(got_it_url)
    vr.redirect(f"{bu}/api/phone/respond?CallSid={call_sid}", method="POST")
    return str(vr)


def append_got_it_and_respond_redirect(response: Any, call_sid: str, base_url: str) -> None:
    """Queue got-it + respond redirect after a media stream (inbound greeting path)."""
    if not _TWILIO_OK or VoiceResponse is None:
        return
    bu = base_url.rstrip("/")
    response.play(f"{bu}/api/phone/got-it-audio?call_sid={call_sid}")
    response.redirect(f"{bu}/api/phone/respond?CallSid={call_sid}", method="POST")


def append_gather_listen(
    response: Any,
    base_url: str,
    *,
    language: str = "en-US",
    nested_play_url: Optional[str] = None,
) -> None:
    """Twilio Gather speech STT → process-speech."""
    if not _TWILIO_OK or VoiceResponse is None:
        return
    bu = base_url.rstrip("/")
    gather = response.gather(
        input="speech",
        action=f"{bu}{PROCESS_SPEECH_PATH}",
        method="POST",
        speech_timeout="auto",
        language=language,
        hints=GATHER_HINTS,
    )
    if nested_play_url:
        gather.play(nested_play_url)
    response.redirect(f"{bu}{PROCESS_SPEECH_PATH}", method="POST")


def append_post_ai_listen_with_still_there(
    response: Any,
    *,
    call_sid: str,
    base_url: str,
    twilio_lang_code: str,
    still_there_play_url: str,
    use_deepgram: bool,
    call_state: dict[str, Any],
) -> None:
    """
    After AI TTS playback: first listen window, Still there?, second listen window.

    Deepgram: two Media Streams; successful speech interrupts via REST (media_ws).
    Gather: native Twilio behavior (speech in gather skips subsequent verbs).
    """
    if use_deepgram:
        gen = next_media_stream_generation(call_state)
        append_connect_stream(
            response, call_sid=call_sid, base_url=base_url, stream_generation=gen
        )
        response.play(still_there_play_url)
        gen2 = next_media_stream_generation(call_state)
        append_connect_stream(
            response, call_sid=call_sid, base_url=base_url, stream_generation=gen2
        )
    else:
        response.gather(
            input="speech",
            action=f"{base_url.rstrip('/')}{PROCESS_SPEECH_PATH}",
            method="POST",
            speech_timeout="auto",
            language=twilio_lang_code,
            hints=GATHER_HINTS,
        )
        response.play(still_there_play_url)
        response.gather(
            input="speech",
            action=f"{base_url.rstrip('/')}{PROCESS_SPEECH_PATH}",
            method="POST",
            speech_timeout="auto",
            language=twilio_lang_code,
            hints=GATHER_HINTS,
        )


def empty_retry_twiml(
    *,
    base_url: str,
    language: str,
    use_deepgram: bool,
    call_sid: str,
    call_state: dict[str, Any],
    prompt_tts_url: Optional[str] = None,
) -> str:
    """Re-prompt after empty STT (Gather or single Deepgram listen)."""
    if not _TWILIO_OK or VoiceResponse is None:
        return '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
    bu = base_url.rstrip("/")
    vr = VoiceResponse()
    if prompt_tts_url:
        vr.play(prompt_tts_url)
    else:
        vr.say(
            "I didn't quite catch that. After the tone, please say that again in a few words.",
            voice="alice",
        )
    if use_deepgram and call_sid:
        gen = next_media_stream_generation(call_state)
        append_connect_stream(vr, call_sid=call_sid, base_url=bu, stream_generation=gen)
        append_got_it_and_respond_redirect(vr, call_sid, base_url)
    else:
        gather = vr.gather(
            input="speech",
            action=f"{bu}{PROCESS_SPEECH_PATH}",
            method="POST",
            speech_timeout="auto",
            timeout=10,
            language=language,
            hints=GATHER_HINTS,
        )
        gather.say("Go ahead.", voice="alice")
    vr.say("We didn't hear anything. Goodbye for now.", voice="alice")
    vr.hangup()
    return str(vr)
