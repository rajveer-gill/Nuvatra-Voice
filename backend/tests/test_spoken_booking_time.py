"""Spoken times must parse, and an unusable one must not vanish.

From a live call on 2026-08-11: the caller said "in the afternoon", the model wrote
time="afternoon", normalize_booking_time returned None, the row was rejected, and
nothing was created — while the reply told the caller their request was in. The prompt
was changed to insist on a clock time, but the parser still couldn't take a spoken one,
so the next caller who said "two in the afternoon" would have been dropped the same way.

Two guarantees here:
  1. Times people actually say parse (and vague half-of-day words still don't).
  2. When a field really is unusable, the caller is re-asked instead of being told
     a request exists that doesn't.
"""

from __future__ import annotations

import pytest

from booking_fields import (
    booking_context_from_business,
    looks_like_booking_time,
    normalize_booking_time,
)
from conversation_service import booking_reject_recovery_text


def _ctx():
    return booking_context_from_business(
        {
            "staff": [{"id": "j1", "name": "Jake"}, {"id": "t1", "name": "Tom"}],
            "services": [{"name": "Short Cut"}, {"name": "Long Cut"}],
        }
    )


# --- 1. spoken times parse -------------------------------------------------


@pytest.mark.parametrize(
    "spoken,expected",
    [
        # The exact phrase that lost a request on the live call.
        ("two in the afternoon", "14:00"),
        ("Two in the afternoon", "14:00"),
        # Bare hour words follow the same salon-hours convention as bare digits:
        # "3" already meant 3 PM, so "three" does too.
        ("two", "14:00"),
        ("three", "15:00"),
        ("two thirty", "14:30"),
        ("two o'clock", "14:00"),
        ("two oclock", "14:00"),
        ("ten fifteen", "10:15"),
        ("eleven forty five", "11:45"),
        ("twelve thirty", "12:30"),
        # "past"/"to" forms
        ("half past three", "15:30"),
        ("quarter past three", "15:15"),
        ("quarter to four", "15:45"),
        # named times
        ("noon", "12:00"),
        ("midday", "12:00"),
        ("midnight", "00:00"),
        # explicit half of the day wins over the bare-hour convention
        ("nine in the morning", "09:00"),
        ("ten thirty in the morning", "10:30"),
        ("seven in the evening", "19:00"),
        ("eight at night", "20:00"),
        # speech filler the model passes through
        ("at two", "14:00"),
        ("around three thirty", "15:30"),
    ],
)
def test_spoken_times_parse(spoken, expected):
    assert normalize_booking_time(spoken) == expected


@pytest.mark.parametrize(
    "vague",
    [
        # A half of the day is not a time. Guessing one would put a slot the caller
        # never chose in front of the salon — worse than re-asking.
        "afternoon",
        "morning",
        "evening",
        "tonight",
        "later",
        "sometime",
        "whenever",
        "soon",
        "asap",
        "",
    ],
)
def test_vague_words_are_still_rejected(vague):
    assert normalize_booking_time(vague) is None


@pytest.mark.parametrize("name", ["Jake", "Tom", "Long Cut", "Short Cut", "Blowout"])
def test_names_and_services_are_not_times(name):
    """The word parser must not turn a misaligned staff/service field into a time."""
    assert normalize_booking_time(name) is None
    assert not looks_like_booking_time(name, _ctx())


@pytest.mark.parametrize(
    "numeric,expected",
    [
        ("2 PM", "14:00"),
        ("3:00 PM", "15:00"),
        ("15:00", "15:00"),
        ("9 AM", "09:00"),
        ("12:30", "12:30"),
        ("3", "15:00"),
    ],
)
def test_numeric_times_unchanged(numeric, expected):
    """Regression guard: the digit path behaves exactly as it did before."""
    assert normalize_booking_time(numeric) == expected


def test_spoken_time_passes_the_booking_time_gate():
    """looks_like_booking_time gates validation; a spoken time has to clear it."""
    assert looks_like_booking_time("two in the afternoon", _ctx())
    assert looks_like_booking_time("half past three", _ctx())


# --- 2. an unusable field is re-asked, not dropped -------------------------


def test_unparseable_time_the_model_filled_in_is_re_asked():
    text = booking_reject_recovery_text("invalid_time", raw_time="afternoon")
    assert text is not None
    assert "time" in text.lower()


def test_still_gathering_is_left_alone():
    """A partial marker with no time yet is normal mid-call: say nothing, let the
    model's own question through. Overriding here would talk over a good question."""
    assert booking_reject_recovery_text("invalid_time", raw_time="") is None
    assert booking_reject_recovery_text("invalid_date", raw_date="") is None


def test_past_and_bad_date_are_re_asked_when_filled():
    assert booking_reject_recovery_text("past_time", raw_time="9 AM") is not None
    assert booking_reject_recovery_text("past_date", raw_date="2020-01-01") is not None
    assert booking_reject_recovery_text("invalid_date", raw_date="next tuesday") is not None


def test_no_recovery_text_when_nothing_was_rejected():
    assert booking_reject_recovery_text(None, raw_time="2 PM") is None


def test_recovery_never_claims_a_request_exists():
    """The bug was the caller being told a request was in when it wasn't. No recovery
    line may imply anything was recorded."""
    for reject, kwargs in (
        ("invalid_time", {"raw_time": "afternoon"}),
        ("past_time", {"raw_time": "9 AM"}),
        ("past_date", {"raw_date": "2020-01-01"}),
        ("invalid_date", {"raw_date": "next tuesday"}),
    ):
        text = (booking_reject_recovery_text(reject, **kwargs) or "").lower()
        assert text
        for claim in ("sent", "booked", "all set", "confirmed", "got everything"):
            assert claim not in text, f"{reject} recovery implies success: {text!r}"
