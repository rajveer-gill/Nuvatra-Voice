"""Regression tests for receptionist system prompt (booking rules, time format, language)."""

import pytest

from prompts.receptionist import (
    appointment_focus_guidance,
    build_system_prompt,
    caller_message_suggests_pricing,
    format_service_catalog_for_prompt,
    latest_user_message,
)


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
    assert "NEVER a stylist" in p or "Never put a stylist name in field 1" in p
    assert "Do NOT ask for email" in p


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
    assert "Do NOT ask callers to pick a service" in p
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


def test_prompt_multi_staff_requires_stylist_question():
    biz = {
        "name": "Test Salon",
        "services": [{"id": "s1", "name": "Haircut", "price": 30, "duration_minutes": 30}],
        "staff": [{"name": "Jamie"}, {"name": "Alex"}],
    }
    p = build_system_prompt(business_info=biz, include_booked_slots=True, booked_slots_prompt_text="")
    assert "Multiple team members" in p
    assert "MUST ask which stylist" in p
    assert "BEFORE asking which service" in p
    assert "ask stylist preference first" in p


def test_prompt_empty_slots_branch(minimal_business):
    p = build_system_prompt(
        business_info=minimal_business,
        include_booked_slots=True,
        booked_slots_prompt_text="",
    )
    assert "Booked slots: none" in p
    assert "ALL times are available" in p


def test_service_catalog_prompt_uses_natural_voice_guidance():
    block = format_service_catalog_for_prompt(
        [
            {"name": "Short Cut", "price": 30, "duration_minutes": 30},
            {"name": "Long Cut", "price": 50, "duration_minutes": 60},
        ]
    )
    assert '"Short Cut"' in block
    assert "VOICE:" in block
    assert "sound like a real receptionist" in block
    assert "($30.0" not in block
    assert "30 min)" not in block


def test_prompt_orients_caller_toward_booking(minimal_business):
    p = build_system_prompt(
        business_info=minimal_business,
        include_booked_slots=True,
        booked_slots_prompt_text="",
    )
    assert "PRIMARY GOAL" in p
    assert "book an appointment" in p.lower()
    assert "unrelated" in p.lower() or "off-topic" in p.lower() or "trivia" in p.lower()


def test_appointment_focus_guidance_sms_off_topic_redirect():
    g = appointment_focus_guidance("Test Spa", include_booked_slots=True, channel="sms")
    assert "book an appointment" in g.lower()
    assert "trivia" in g.lower() or "unrelated" in g.lower()


def test_prompt_services_not_robotic_price_list():
    biz = {
        "name": "Test Salon",
        "services": [
            {"id": "s1", "name": "Short Cut", "price": 30, "duration_minutes": 30},
            {"id": "s2", "name": "Long Cut", "price": 50, "duration_minutes": 60},
        ],
        "staff": [{"name": "Jamie"}],
    }
    p = build_system_prompt(business_info=biz, include_booked_slots=False)
    assert "Services menu" in p
    assert "VOICE:" in p
    assert "Short Cut ($30.0, 30 min)" not in p
    assert "Pricing:" in p
    assert "how much" in p.lower() or "cost" in p.lower()


def test_caller_message_suggests_pricing():
    assert caller_message_suggests_pricing("How much is a long cut?")
    assert caller_message_suggests_pricing("What's the price for short cut")
    assert not caller_message_suggests_pricing("Book me for tomorrow at 3")


def test_service_catalog_includes_price_answer_guidance():
    block = format_service_catalog_for_prompt(
        [{"name": "Long Cut", "price": 50, "duration_minutes": 45}]
    )
    assert "Never say you do not know" in block
    assert "$50" in block


def test_service_catalog_without_prices_configured():
    block = format_service_catalog_for_prompt(
        [{"name": "Long Cut", "price": 0, "duration_minutes": 45}]
    )
    assert "not configured" in block.lower() or "confirm" in block.lower()


def test_voice_booking_nudge_prioritizes_pricing_question(monkeypatch):
    from main import _voice_booking_nudge_message

    monkeypatch.setattr(
        "main.get_business_info",
        lambda: {
            "staff": [{"id": "j1", "name": "Jake"}],
            "services": [{"id": "s1", "name": "Long Cut", "price": 50, "duration_minutes": 45}],
        },
    )
    history = [
        {"role": "user", "content": "I want to book with Jake tomorrow"},
        {"role": "assistant", "content": "Sure"},
        {"role": "user", "content": "How much is a long cut?"},
    ]
    nudge = _voice_booking_nudge_message(history)
    assert nudge is not None
    assert "price" in nudge.lower()
    assert "not off-topic" in nudge.lower()
    assert "BOOKING:" not in nudge
