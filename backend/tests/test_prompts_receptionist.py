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
    minimal_business["staff"] = [{"id": "s1", "name": "Jamie", "phone": "+15551110001"}]
    minimal_business["transfer_targets"] = [{"staff_id": "s1", "phone": "+15551110001"}]
    p = build_system_prompt(business_info=minimal_business, include_booked_slots=False)
    assert "TRANSFER_TO:" in p
    assert "Jamie" in p


def test_prompt_staff_notes_reference_block(minimal_business):
    minimal_business["staff"] = [
        {"name": "Jamie", "notes": "Best for massage bookings."},
    ]
    p = build_system_prompt(business_info=minimal_business, include_booked_slots=False)
    assert "Business-entered facts about staff" in p
    assert "Jamie" in p
    assert "massage" in p.lower()


def test_prompt_includes_receptionist_name(minimal_business):
    minimal_business["receptionist_name"] = "Ava"
    p = build_system_prompt(business_info=minimal_business, include_booked_slots=False)
    assert "Your name is Ava" in p


def test_prompt_non_english_locks_language(minimal_business):
    p = build_system_prompt(
        business_info=minimal_business,
        detected_language="Spanish",
        include_booked_slots=False,
    )
    assert "Spanish" in p
    assert "MUST respond ONLY in Spanish" in p


def test_prompt_no_services_skips_service_questions():
    biz = {
        "name": "Test Spa",
        "hours": "9-5",
        "services": [],
        "staff": [{"name": "Jamie"}],
    }
    p = build_system_prompt(
        business_info=biz,
        include_booked_slots=True,
        booked_slots_prompt_text="",
    )
    assert "NOT configured a service menu" in p
    assert "Do NOT ask callers to choose a service" in p
    assert "- Services:" not in p.split("You can help with:")[1].split("staff")[0]


def test_prompt_staff_linked_services(minimal_business):
    minimal_business["services"] = [
        {"id": "svc-a", "name": "Haircut", "price": 40, "duration_minutes": 30},
        {"id": "svc-b", "name": "Color", "price": 80, "duration_minutes": 90},
    ]
    minimal_business["staff"] = [
        {"name": "Jamie", "service_ids": ["svc-a"]},
        {"name": "Alex", "service_ids": []},
    ]
    p = build_system_prompt(business_info=minimal_business, include_booked_slots=False)
    assert "Staff and which services they provide" in p
    assert "Jamie: Haircut" in p
    assert "Alex: any listed service" in p


def test_prompt_empty_slots_branch(minimal_business):
    p = build_system_prompt(
        business_info=minimal_business,
        include_booked_slots=True,
        booked_slots_prompt_text="",
    )
    assert "Booked slots: none" in p
    assert "ALL times are available" in p
