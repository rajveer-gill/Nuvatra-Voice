"""Streaming TTS → Twilio μ-law frames (Option C: bidirectional media streaming).

Unlike the batch `/api/phone/tts-audio` path (synthesize the whole mp3, then <Play>), this
requests OpenAI TTS as a *stream* of raw PCM and transcodes each chunk to 8 kHz μ-law 20 ms
frames as it arrives — so the first frame can be sent to Twilio within a few hundred ms of
the reply text being ready, instead of waiting ~2-4s for the full clip.

Kept separate from streaming_audio.py (which is pure/dependency-free and fully unit-tested)
because this module reaches the OpenAI client via runtime.
"""
from __future__ import annotations

from typing import Iterator

import runtime
from voice.streaming_audio import Pcm24kToMulaw8k, frame_mulaw

# OpenAI streaming TTS emits 24 kHz signed-16 PCM when response_format="pcm".
_PCM_READ_CHUNK = 4096


def stream_tts_ulaw_frames(
    text: str,
    voice: str,
    *,
    model: str = "tts-1",
    speed: float = 1.0,
) -> Iterator[bytes]:
    """Yield consecutive 160-byte (20 ms) μ-law/8000 frames for `text`.

    Frames are produced incrementally as OpenAI streams PCM, so the caller can start sending
    audio to Twilio immediately. A trailing partial frame is zero(silence)-padded on flush.
    """
    text = (text or "").strip()
    if not text:
        return
    transcoder = Pcm24kToMulaw8k()
    carry = bytearray()
    with runtime.client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text,
        response_format="pcm",
        speed=speed,
    ) as response:
        for pcm_chunk in response.iter_bytes(chunk_size=_PCM_READ_CHUNK):
            if not pcm_chunk:
                continue
            mulaw = transcoder.feed(pcm_chunk)
            if mulaw:
                for frame in frame_mulaw(mulaw, carry):
                    yield frame
    tail = transcoder.flush()
    for frame in frame_mulaw(tail, carry, flush=True):
        yield frame
