"""Tests for appointment time parsing (AM/PM)."""

import os

import pytest


@pytest.fixture(autouse=True)
def _clear_twilio_token(monkeypatch):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)


def test_time_to_minutes_pm_not_stripped_to_am():
    from main import _normalize_time_to_hhmm, _time_to_minutes

    assert _time_to_minutes("2:00 PM") == 14 * 60
    assert _normalize_time_to_hhmm("2:00 PM") == "14:00"
    assert _normalize_time_to_hhmm("3:00 PM") == "15:00"


def test_time_to_minutes_bare_afternoon_hour():
    from main import _normalize_time_to_hhmm

    assert _normalize_time_to_hhmm("2") == "14:00"
    assert _normalize_time_to_hhmm("3") == "15:00"


def test_time_to_minutes_morning():
    from main import _normalize_time_to_hhmm

    assert _normalize_time_to_hhmm("10:00 AM") == "10:00"
    assert _normalize_time_to_hhmm("9") == "09:00"
