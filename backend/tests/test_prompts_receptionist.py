"""Regression tests for receptionist system prompt (booking rules, time format, language)."""

import pytest

from prompts.receptionist import build_system_prompt


@pytest.fixture
def minimal_business():
    return {
        "name": "Test Spa",
        "hours": "9-5",
        "services": ["Massage"],
        "staff": [{"name": "Jamie"}],
        "business_type": "spa",
    }


def test_prompt_contains_booking_token_format(minimal_business):
    p = build_system_prompt(
        business_info=minimal_business,
        include_booked_slots=True,
        booked_slots_prompt_text="Booked slots (do not double-book): 2026-04-28 at 1:00 PM.",
    )
    assert "BOOKING:" in p
    assert "name|phone|email|date|time|reason" in p


def test_prompt_requires_12_hour_spoken_times(minimal_business):
    p = build_system_prompt(
        business_info=minimal_business,
        include_booked_slots=True,
        booked_slots_prompt_text="x",
    )
    assert "12-hour format with AM/PM" in p
    assert "24-hour/military" in p or "13:00" in p


def test_prompt_repeat_caller_memory(minimal_business):
    p = build_system_prompt(
        business_info=minimal_business,
        caller_memory={"name": "Alex", "call_count": 2, "last_reason": "booking"},
        include_booked_slots=False,
    )
    assert "REPEAT CALLER" in p
    assert "Alex" in p


def test_prompt_staff_transfer_instruction(minimal_business):
    p = build_system_prompt(business_info=minimal_business, include_booked_slots=False)
    assert "TRANSFER_TO:" in p
    assert "Jamie" in p


def test_prompt_non_english_locks_language(minimal_business):
    p = build_system_prompt(
        business_info=minimal_business,
        detected_language="Spanish",
        include_booked_slots=False,
    )
    assert "Spanish" in p
    assert "MUST respond ONLY in Spanish" in p


def test_prompt_empty_slots_branch(minimal_business):
    p = build_system_prompt(
        business_info=minimal_business,
        include_booked_slots=True,
        booked_slots_prompt_text="",
    )
    assert "Booked slots: none" in p
    assert "ALL times are available" in p
