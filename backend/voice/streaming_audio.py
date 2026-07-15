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

import math
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


def _design_lowpass(num_taps: int, fc_hz: float, fs_hz: float) -> List[float]:
    """Windowed-sinc (Hamming) low-pass FIR, DC gain normalized to 1.0.

    A proper anti-alias filter with a sharp cutoff just under the 4 kHz output Nyquist —
    preserves the 2-4 kHz speech band (consonant clarity) that a crude box average smears,
    which is what made the streamed audio sound muffled.
    """
    m = (num_taps - 1) / 2.0
    taps: List[float] = []
    for n in range(num_taps):
        x = n - m
        sinc = (2 * fc_hz / fs_hz) if x == 0 else math.sin(2 * math.pi * fc_hz / fs_hz * x) / (math.pi * x)
        window = 0.54 - 0.46 * math.cos(2 * math.pi * n / (num_taps - 1))
        taps.append(sinc * window)
    total = sum(taps)
    return [t / total for t in taps]


# 23-tap low-pass at fc=3600 Hz for 24 kHz input. Computed only at decimated output positions
# (polyphase), so cost is ~ (samples/3)*taps — cheap enough for real-time on one core.
_LPF = _design_lowpass(23, 3600.0, 24000.0)
_LPF_N = len(_LPF)


class Pcm24kToMulaw8k:
    """Streaming transcoder: feed arbitrary 24 kHz/16-bit/mono PCM byte chunks, get back
    μ-law/8000 bytes. A windowed-sinc low-pass is applied before 3:1 decimation. State
    (sample history, decimation phase, odd trailing byte) carries across chunks so output is
    identical regardless of how the PCM stream is split.
    """

    def __init__(self) -> None:
        self._byte_rem = b""             # leftover odd byte across chunks
        self._hist: List[int] = [0] * (_LPF_N - 1)  # last N-1 input samples (zero-primed)
        self._pos = 0                    # absolute input-sample counter (for decimation phase)

    def feed(self, pcm: bytes) -> bytes:
        data = self._byte_rem + pcm
        ns = len(data) // 2
        if ns == 0:
            self._byte_rem = data
            return b""
        new = [int.from_bytes(data[2 * i : 2 * i + 2], "little", signed=True) for i in range(ns)]
        self._byte_rem = data[2 * ns :]
        buf = self._hist + new           # buf index = hlen + i  ->  input sample `new[i]`
        hlen = len(self._hist)
        taps = _LPF
        n = _LPF_N
        out = bytearray()
        base = self._pos
        for i in range(ns):
            if (base + i) % _DECIMATION == 0:
                bi = hlen + i            # current sample's index in buf; window = buf[bi-n+1 .. bi]
                acc = 0.0
                w = buf[bi - n + 1 : bi + 1]
                for k in range(n):
                    acc += taps[k] * w[k]
                out.append(linear16_to_ulaw(int(round(acc))))
        self._pos = base + ns
        self._hist = buf[-(n - 1) :]
        return bytes(out)

    def flush(self) -> bytes:
        """Trailing ≤2 samples not landing on a decimation position are inaudible; drop them."""
        self._byte_rem = b""
        return b""


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
