"""TwiML snippets for Gather fallback when Deepgram / media stream fails."""

from __future__ import annotations

try:
    from twilio.twiml.voice_response import VoiceResponse

    _TWILIO_OK = True
except ImportError:
    VoiceResponse = None  # type: ignore[misc, assignment]
    _TWILIO_OK = False


def gather_process_speech_twiml(call_sid: str, base_url: str) -> str:
    """Speech Gather → process-speech after a failed media stream (no repeated greeting)."""
    if not _TWILIO_OK or VoiceResponse is None:
        return '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
    bu = base_url.rstrip("/")
    _ = call_sid  # reserved for future per-call hints / logging
    vr = VoiceResponse()
    vr.gather(
        input="speech",
        action=f"{bu}/api/phone/process-speech",
        method="POST",
        speech_timeout="auto",
        language="en-US",
        hints="appointment, schedule, message, hours, contact, help",
    )
    vr.redirect(f"{bu}/api/phone/process-speech", method="POST")
    return str(vr)
