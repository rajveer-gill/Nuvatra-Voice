"""Streaming TTS frame generator (Option C) with a faked OpenAI streaming response."""
import struct
from contextlib import contextmanager

import runtime
from voice import streaming_tts
from voice.streaming_audio import MULAW_FRAME_BYTES


class _FakeStreamingResponse:
    def __init__(self, pcm: bytes, chunk: int):
        self._pcm = pcm
        self._chunk = chunk

    def iter_bytes(self, chunk_size=4096):
        for i in range(0, len(self._pcm), self._chunk):
            yield self._pcm[i : i + self._chunk]


def _install_fake_openai(monkeypatch, pcm: bytes, chunk: int = 4096):
    @contextmanager
    def fake_create(**kwargs):
        assert kwargs["response_format"] == "pcm"  # must request raw PCM to transcode
        yield _FakeStreamingResponse(pcm, chunk)

    fake_client = type(
        "C", (), {"audio": type("A", (), {"speech": type("S", (), {
            "with_streaming_response": type("W", (), {"create": staticmethod(fake_create)})()
        })()})()}
    )()
    monkeypatch.setattr(runtime, "client", fake_client, raising=False)


def test_empty_text_yields_nothing(monkeypatch):
    _install_fake_openai(monkeypatch, b"")
    assert list(streaming_tts.stream_tts_ulaw_frames("   ", "fable")) == []


def test_frames_are_160_bytes_and_cover_all_audio(monkeypatch):
    # 9000 PCM samples @ 24 kHz -> 3000 μ-law bytes @ 8 kHz -> 18 full 160-byte frames + pad.
    pcm = b"".join(struct.pack("<h", (i % 1000) - 500) for i in range(9000))
    _install_fake_openai(monkeypatch, pcm, chunk=4096)
    frames = list(streaming_tts.stream_tts_ulaw_frames("hello there", "fable"))
    assert all(len(f) == MULAW_FRAME_BYTES for f in frames)
    # 3000 μ-law bytes / 160 = 18.75 -> 19 frames (last one silence-padded).
    assert len(frames) == 19


def test_streaming_independent_of_chunk_boundaries(monkeypatch):
    pcm = b"".join(struct.pack("<h", (i * 7 % 2000) - 1000) for i in range(6000))
    _install_fake_openai(monkeypatch, pcm, chunk=4096)
    big = list(streaming_tts.stream_tts_ulaw_frames("x", "fable"))
    _install_fake_openai(monkeypatch, pcm, chunk=101)  # awkward chunk size
    small = list(streaming_tts.stream_tts_ulaw_frames("x", "fable"))
    assert big == small  # frame output must not depend on how PCM is chunked
