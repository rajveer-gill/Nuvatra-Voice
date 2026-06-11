"""Wait-loop filler progression: no broken-record 'One moment.' on a loop.

The caller already hears "Got it, one moment." before polling starts, so the first
poll stays silent and later polls alternate phrases. Covers the pure phrase picker
and the TwiML-appending helper's per-call counter.
"""

from unittest.mock import MagicMock

import voice_service
from routers import phone


def test_first_poll_is_silent():
    assert voice_service.pending_filler_for_poll(0) is None


def test_later_polls_alternate_and_never_lead_with_one_moment():
    phrases = voice_service.PENDING_FILLER_PHRASES
    first = voice_service.pending_filler_for_poll(1)
    assert first == (0, phrases[0])
    # The very first spoken filler must not repeat "One moment." (already in the
    # "Got it, one moment." the caller just heard).
    assert first[1].lower() != "one moment."
    # Distinct consecutive phrases, wrapping cleanly.
    assert voice_service.pending_filler_for_poll(2) == (1, phrases[1])
    assert voice_service.pending_filler_for_poll(3) == (2, phrases[2])
    assert voice_service.pending_filler_for_poll(4) == (0, phrases[0])  # wraps


def _fake_response():
    r = MagicMock()
    r.calls = []
    r.play.side_effect = lambda url: r.calls.append(("play", url))
    r.pause.side_effect = lambda length=None: r.calls.append(("pause", length))
    r.redirect.side_effect = lambda url, method=None: r.calls.append(("redirect", url))
    return r


def test_append_filler_first_poll_no_audio(monkeypatch):
    store = MagicMock()
    store.sessions = {"CA1": {"respond_poll_count": 0}}
    merged = {}
    store.merge_session.side_effect = lambda sid, updates: merged.update(updates)
    monkeypatch.setattr("runtime.call_store", store)

    r = _fake_response()
    phone._append_pending_filler(r, "https://x.test", "CA1")

    kinds = [c[0] for c in r.calls]
    assert "play" not in kinds          # silent first poll
    assert "pause" in kinds and "redirect" in kinds
    assert merged["respond_poll_count"] == 1  # counter advanced


def test_append_filler_second_poll_plays_varied_clip(monkeypatch):
    store = MagicMock()
    store.sessions = {"CA1": {"respond_poll_count": 1}}
    merged = {}
    store.merge_session.side_effect = lambda sid, updates: merged.update(updates)
    monkeypatch.setattr("runtime.call_store", store)

    r = _fake_response()
    phone._append_pending_filler(r, "https://x.test", "CA1")

    plays = [c[1] for c in r.calls if c[0] == "play"]
    assert len(plays) == 1
    assert "/api/phone/filler-audio" in plays[0] and "i=0" in plays[0]
    assert merged["respond_poll_count"] == 2
