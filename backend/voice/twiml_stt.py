"""
TwiML builders for voice STT: Deepgram (Media Streams) or Twilio Gather fallback.

All listen turns should go through these helpers so VOICE_STT_PROVIDER=deepgram applies
to every conversational turn, not only the first inbound greeting.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

from observability import voice_trace, voice_warning
from voice.call_sid import normalize_call_sid
from voice.call_session_store import get_call_session_store
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
NO_SPEECH_PATH = "/api/phone/no-speech"


def next_media_stream_generation(call_sid: str, call_state: dict[str, Any] | None = None) -> int:
    """
    Monotonic generation per call; bound into stream tokens to block replay.

    Uses CallSessionStore.incr_media_stream_gen (atomic on Redis) so generation
    is persisted before Twilio opens the Media Stream WebSocket.
    """
    sid = normalize_call_sid(call_sid)
    if not sid:
        voice_warning("media_stream_gen_invalid_call_sid")
        return 0
    g = get_call_session_store().incr_media_stream_gen(sid)
    if g < 1:
        voice_warning("media_stream_gen_incr_failed", call_sid=sid)
        return 0
    if call_state is not None:
        call_state["media_stream_gen"] = g
    return g


def append_connect_stream(
    response: Any,
    *,
    call_sid: str,
    base_url: str,
    stream_generation: int,
) -> bool:
    """Append <Connect><Stream> with signed token. Returns False if stream omitted (fail-closed)."""
    if not _TWILIO_OK or Connect is None or Stream is None:
        return False
    sid = normalize_call_sid(call_sid)
    if not sid or stream_generation < 1:
        voice_warning(
            "connect_stream_skipped",
            call_sid=sid or str(call_sid)[:8],
            stream_generation=stream_generation,
        )
        return False
    bu = base_url.rstrip("/")
    wss_base = http_to_ws_base(bu)
    stream_url = f"{wss_base}/api/phone/media"
    token = mint_media_stream_token(sid, stream_generation=stream_generation)
    if not token:
        voice_warning("connect_stream_skipped_no_token", call_sid=sid)
        return False
    connect = Connect()
    stream = Stream(url=stream_url)
    stream.parameter(name="token", value=token)
    connect.append(stream)
    response.append(connect)
    return True


def bidirectional_stream_twiml(
    *,
    call_sid: str,
    base_url: str,
    stream_generation: int,
    record_callback_url: Optional[str] = None,
) -> Optional[str]:
    """Full TwiML for an Option C call: one persistent bidirectional <Connect><Stream> that
    stays open for the whole call (Connect blocks until the WS closes). The handler at
    /api/phone/media-stream does greeting, listening, and streams the AI reply as outbound
    audio over the same socket. Returns None if TwiML/token can't be built (caller falls back
    to the <Play> path). Optional <Start><Recording> is emitted before Connect when configured.
    """
    if not _TWILIO_OK or VoiceResponse is None or Connect is None or Stream is None:
        return None
    sid = normalize_call_sid(call_sid)
    if not sid or stream_generation < 1:
        voice_warning("bidi_stream_skipped", call_sid=sid or str(call_sid)[:8], gen=stream_generation)
        return None
    token = mint_media_stream_token(sid, stream_generation=stream_generation)
    if not token:
        voice_warning("bidi_stream_skipped_no_token", call_sid=sid)
        return None
    bu = base_url.rstrip("/")
    wss_base = http_to_ws_base(bu)
    vr = VoiceResponse()
    if record_callback_url:
        start = vr.start()
        start.recording(
            channels="dual",
            recording_status_callback=record_callback_url,
            recording_status_callback_method="POST",
        )
    connect = Connect()
    stream = Stream(url=f"{wss_base}/api/phone/media-stream")
    stream.parameter(name="token", value=token)
    connect.append(stream)
    vr.append(connect)
    return str(vr)


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


def append_deepgram_silence_followup_after_stream(
    response: Any,
    *,
    call_sid: str,
    base_url: str,
    still_there_play_url: str,
    call_state: dict[str, Any],
) -> None:
    """
    After the first post-greeting Media Stream: Still there?, second listen, then no-speech webhook.

    Caller speech on either stream interrupts via REST (media_ws) with got-it + respond — never
    queue those verbs here (that caused immediate /respond before the caller spoke).
    """
    if not _TWILIO_OK:
        return
    response.play(still_there_play_url)
    gen2 = next_media_stream_generation(call_sid, call_state)
    append_connect_stream(
        response, call_sid=call_sid, base_url=base_url, stream_generation=gen2
    )
    voice_trace(
        "listen_windows_complete_redirect_no_speech",
        call_sid=call_sid,
        stt="deepgram",
        phase="post_greeting",
    )
    response.redirect(f"{base_url.rstrip('/')}{NO_SPEECH_PATH}", method="POST")


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
        gen = next_media_stream_generation(call_sid, call_state)
        append_connect_stream(
            response, call_sid=call_sid, base_url=base_url, stream_generation=gen
        )
        response.play(still_there_play_url)
        gen2 = next_media_stream_generation(call_sid, call_state)
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

    voice_trace(
        "listen_windows_complete_redirect_no_speech",
        call_sid=call_sid,
        stt="deepgram" if use_deepgram else "twilio",
    )
    response.redirect(f"{base_url.rstrip('/')}{NO_SPEECH_PATH}", method="POST")


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
        gen = next_media_stream_generation(call_sid, call_state)
        append_connect_stream(vr, call_sid=call_sid, base_url=bu, stream_generation=gen)
        # Silence falls through to goodbye below; speech uses REST update in media_ws.
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
