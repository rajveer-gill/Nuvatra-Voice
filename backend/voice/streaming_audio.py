"""Pure-Python audio transcoding for outbound Twilio bidirectional Media Streams.

Twilio's bidirectional stream wants outbound audio as base64 **raw mulaw/8000 mono**
(G.711 μ-law, 8 kHz, no file header). OpenAI streaming TTS emits **pcm** = 24 kHz,
16-bit signed little-endian mono. So per streamed chunk we downsample 24k→8k and μ-law
encode, then slice into 20 ms (160-byte) frames for paced sending.

Deliberately dependency-free: the `audioop` module (lin2ulaw/ratecv) was removed in
Python 3.13, so it can't be relied on across versions or unit-tested on 3.13+. These
routines are the standard G.711 algorithm and a 3:1 averaging decimator, verifiable on
any Python.
"""
from __future__ import annotations

from typing import List

# Twilio telephony frame: 8000 Hz * 20 ms = 160 μ-law bytes per frame.
MULAW_FRAME_BYTES = 160

# OpenAI TTS pcm is 24 kHz; Twilio wants 8 kHz → decimate by 3.
_PCM_RATE = 24000
_MULAW_RATE = 8000
_DECIMATION = _PCM_RATE // _MULAW_RATE  # 3

# G.711 μ-law constants (14-bit variant, matching CPython audioop.lin2ulaw byte-for-byte
# — verified against audioop across all 65536 int16 inputs).
_ULAW_BIAS = 0x84
_ULAW_CLIP_14 = 8159
_SEG_UEND = (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF)


def _seg_search(val: int) -> int:
    for i, end in enumerate(_SEG_UEND):
        if val <= end:
            return i
    return 8


def linear16_to_ulaw(sample: int) -> int:
    """Encode one signed 16-bit PCM sample to an 8-bit G.711 μ-law byte.

    Reproduces CPython's audioop.lin2ulaw (14-bit variant) exactly, so audio matches what
    the removed stdlib module would have produced.
    """
    sample = sample >> 2  # 16-bit -> 14-bit (arithmetic shift)
    if sample < 0:
        sample = -sample
        mask = 0x7F
    else:
        mask = 0xFF
    if sample > _ULAW_CLIP_14:
        sample = _ULAW_CLIP_14
    sample += _ULAW_BIAS >> 2
    seg = _seg_search(sample)
    if seg >= 8:
        return (0x7F ^ mask) & 0xFF
    uval = ((seg << 4) | ((sample >> (seg + 1)) & 0xF)) & 0xFF
    return (uval ^ mask) & 0xFF


class Pcm24kToMulaw8k:
    """Streaming transcoder: feed arbitrary 24 kHz/16-bit/mono PCM byte chunks, get back
    μ-law/8000 bytes. Buffers partial sample-groups across chunks so chunk boundaries that
    don't align to 3-sample (6-byte) groups don't drop or corrupt audio.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, pcm: bytes) -> bytes:
        """Transcode as much of the accumulated PCM as forms whole 3-sample groups."""
        if pcm:
            self._buf.extend(pcm)
        n = len(self._buf)
        group = 2 * _DECIMATION  # 6 bytes = 3 int16 samples
        usable = (n // group) * group
        if usable == 0:
            return b""
        out = bytearray(usable // group)
        buf = self._buf
        for oi, i in enumerate(range(0, usable, group)):
            s0 = int.from_bytes(buf[i : i + 2], "little", signed=True)
            s1 = int.from_bytes(buf[i + 2 : i + 4], "little", signed=True)
            s2 = int.from_bytes(buf[i + 4 : i + 6], "little", signed=True)
            # Average the 3 samples (crude low-pass) before decimating, to limit aliasing.
            out[oi] = linear16_to_ulaw((s0 + s1 + s2) // _DECIMATION)
        del self._buf[:usable]
        return bytes(out)

    def flush(self) -> bytes:
        """Encode any trailing 1-2 leftover samples (pad the group by repeating the last)."""
        if len(self._buf) < 2:
            self._buf.clear()
            return b""
        samples = []
        for i in range(0, len(self._buf) - 1, 2):
            samples.append(int.from_bytes(self._buf[i : i + 2], "little", signed=True))
        self._buf.clear()
        if not samples:
            return b""
        avg = sum(samples) // len(samples)
        return bytes([linear16_to_ulaw(avg)])


def frame_mulaw(data: bytes, carry: bytearray, *, flush: bool = False) -> List[bytes]:
    """Accumulate μ-law bytes in `carry` and pop full 160-byte (20 ms) frames.

    Returns the list of complete frames; leftover stays in `carry`. When flush=True, a final
    short remainder is zero-padded (μ-law silence = 0xFF) to a full frame so it still plays.
    """
    if data:
        carry.extend(data)
    frames: List[bytes] = []
    while len(carry) >= MULAW_FRAME_BYTES:
        frames.append(bytes(carry[:MULAW_FRAME_BYTES]))
        del carry[:MULAW_FRAME_BYTES]
    if flush and carry:
        pad = MULAW_FRAME_BYTES - len(carry)
        frames.append(bytes(carry) + b"\xff" * pad)
        carry.clear()
    return frames
