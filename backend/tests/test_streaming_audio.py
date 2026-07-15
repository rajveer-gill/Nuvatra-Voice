"""Transcoding for outbound Twilio bidirectional media (pure-Python μ-law + 24k→8k)."""
import math
import struct

import pytest

from voice.streaming_audio import (
    _LPF,
    MULAW_FRAME_BYTES,
    Pcm24kToMulaw8k,
    frame_mulaw,
    linear16_to_ulaw,
)


def _lpf_mag(freq_hz: float, fs_hz: float = 24000.0) -> float:
    re = sum(t * math.cos(2 * math.pi * freq_hz * k / fs_hz) for k, t in enumerate(_LPF))
    im = sum(t * math.sin(2 * math.pi * freq_hz * k / fs_hz) for k, t in enumerate(_LPF))
    return math.hypot(re, im)


def test_lowpass_preserves_speech_and_kills_aliasing():
    """The anti-alias filter must pass the speech band (so audio isn't muffled) and strongly
    attenuate content above the 4 kHz output Nyquist (so it doesn't alias)."""
    assert _lpf_mag(300) > 0.95     # low speech preserved (near unity)
    assert _lpf_mag(3000) > 0.6     # upper speech band kept -> consonant clarity
    assert _lpf_mag(6000) < 0.15    # above Nyquist: strongly attenuated


def test_ulaw_known_boundaries():
    """Standard G.711 μ-law anchors: 0 -> 0xFF, and sign bit set for negatives."""
    assert linear16_to_ulaw(0) == 0xFF
    # Positive and negative of the same magnitude differ only in the sign bit (0x80).
    assert linear16_to_ulaw(1000) ^ linear16_to_ulaw(-1000) == 0x80


def test_ulaw_matches_reference_if_available():
    """If an audioop implementation is importable (audioop on <3.13, or audioop-lts),
    our pure-Python encoder must match it byte-for-byte across the sample range."""
    audioop = pytest.importorskip("audioop")
    samples = list(range(-32768, 32768, 137))  # sweep the whole int16 range
    raw = b"".join(struct.pack("<h", s) for s in samples)
    ref = audioop.lin2ulaw(raw, 2)
    ours = bytes(linear16_to_ulaw(s) for s in samples)
    assert ours == ref


def test_resampler_output_rate_is_one_third():
    """3 input samples (24 kHz) collapse to 1 μ-law byte (8 kHz)."""
    tc = Pcm24kToMulaw8k()
    pcm = b"".join(struct.pack("<h", v) for v in [100, 200, 300, 400, 500, 600])  # 6 samples
    out = tc.feed(pcm)
    assert len(out) == 2  # 6 samples / 3 -> 2 μ-law bytes


def test_resampler_buffers_partial_groups_across_chunks():
    """A chunk split mid-group must not drop or duplicate audio."""
    samples = list(range(0, 300, 10))  # 30 samples -> expect 10 μ-law bytes total
    pcm = b"".join(struct.pack("<h", s) for s in samples)
    tc_whole = Pcm24kToMulaw8k()
    whole = tc_whole.feed(pcm) + tc_whole.flush()

    tc_split = Pcm24kToMulaw8k()
    # Split at a byte offset that lands in the middle of a 6-byte group.
    a = tc_split.feed(pcm[:7])
    b = tc_split.feed(pcm[7:])
    split = a + b + tc_split.flush()
    assert whole == split
    assert len(whole) == 10


def test_frame_mulaw_pops_full_frames_and_keeps_remainder():
    carry = bytearray()
    frames = frame_mulaw(b"\x00" * (MULAW_FRAME_BYTES + 40), carry)
    assert len(frames) == 1
    assert len(frames[0]) == MULAW_FRAME_BYTES
    assert len(carry) == 40  # remainder held for next chunk


def test_frame_mulaw_flush_pads_last_frame_with_silence():
    carry = bytearray(b"\x01" * 40)
    frames = frame_mulaw(b"", carry, flush=True)
    assert len(frames) == 1
    assert len(frames[0]) == MULAW_FRAME_BYTES
    assert frames[0][40:] == b"\xff" * (MULAW_FRAME_BYTES - 40)  # μ-law silence pad
    assert len(carry) == 0
