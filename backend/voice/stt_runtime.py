"""Runtime selection of voice STT provider (Twilio Gather vs Deepgram media stream)."""

from __future__ import annotations

import logging
from typing import Any

from voice.stt_config import deepgram_api_key, media_stream_signing_secret, voice_stt_provider

_log = logging.getLogger("nuvatra")


def deepgram_stt_active(*, twilio_available: bool, twilio_client: Any) -> bool:
    """
    True when inbound/ongoing turns should use Twilio Media Streams + Deepgram Nova-2.

    Requires env, credentials, and a working Twilio REST client (for fail-open Gather updates).
    """
    if voice_stt_provider() != "deepgram":
        return False
    if not deepgram_api_key():
        _log.warning(
            "[VOICE] VOICE_STT_PROVIDER=deepgram but DEEPGRAM_API_KEY is unset; falling back to Twilio Gather"
        )
        return False
    if not media_stream_signing_secret():
        _log.warning(
            "[VOICE] VOICE_STT_PROVIDER=deepgram but MEDIA_STREAM_SIGNING_SECRET and TWILIO_AUTH_TOKEN "
            "are unset; cannot sign media WebSocket; falling back to Twilio Gather"
        )
        return False
    if not twilio_available or not twilio_client:
        _log.warning("[VOICE] VOICE_STT_PROVIDER=deepgram but Twilio client is unavailable")
        return False
    return True
