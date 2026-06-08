"""Tests for booking_fields sanitization and validation."""

from booking_fields import (
    assistant_asked_service_recently,
    booking_context_from_business,
    looks_like_booking_time,
    normalize_and_validate_booking,
    sanitize_parsed_booking,
    service_choice_resolved,
    service_prompt_message,
    user_affirmed_after_service_prompt,
)


def _ctx():
    return booking_context_from_business(
        {
            "staff": [{"id": "j1", "name": "Jake"}, {"id": "t1", "name": "Tom"}],
            "services": [
                {"name": "Short Cut"},
                {"name": "Long Cut"},
            ],
        }
    )


def test_rejects_stylist_name_as_time():
    ctx = _ctx()
    assert not looks_like_booking_time("Jake", ctx)
    assert not looks_like_booking_time("Tom", ctx)


def test_accepts_valid_times():
    ctx = _ctx()
    assert looks_like_booking_time("15:00", ctx)
    assert looks_like_booking_time("3:00 PM", ctx)
    assert looks_like_booking_time("3", ctx)


def test_sanitize_moves_staff_from_time_slot():
    ctx = _ctx()
    booking = {
        "name": "Raj",
        "date": "2026-06-09",
        "time": "Jake",
        "reason": "",
        "staff": "",
    }
    out, repairs = sanitize_parsed_booking(booking, ctx)
    assert out["staff"] == "Jake"
    assert out["time"] == ""
    assert "staff_from_time" in repairs


def test_normalize_rejects_jake_time_even_after_empty():
    ctx = _ctx()
    booking = {
        "name": "Raj",
        "date": "2026-06-09",
        "time": "Jake",
        "reason": "Long Cut",
        "staff": "",
    }
    prepared, repairs, reject = normalize_and_validate_booking(booking, ctx)
    assert prepared is None
    assert reject == "invalid_time"
    assert "staff_from_time" in repairs


def test_normalize_accepts_repaired_booking_with_time():
    ctx = _ctx()
    booking = {
        "name": "Raj",
        "date": "2026-06-09",
        "time": "15:00",
        "reason": "Long Cut",
        "staff": "Jake",
    }
    prepared, repairs, reject = normalize_and_validate_booking(booking, ctx)
    assert reject is None
    assert prepared is not None
    assert prepared["time"] == "15:00"


def test_assistant_asked_service_recently_detects_prompt():
    history = [
        {"role": "assistant", "content": "Which service would you like with Jake?"},
        {"role": "user", "content": "umm"},
    ]
    assert assistant_asked_service_recently(history)


def test_service_choice_resolved_when_user_named_service():
    ctx = _ctx()
    history = [
        {"role": "assistant", "content": "Which service with Jake?"},
        {"role": "user", "content": "Long cut please"},
    ]
    assert service_choice_resolved(history, ctx, canonical_service="Long Cut")


def test_service_choice_resolved_on_yes_after_service_list():
    ctx = _ctx()
    history = [
        {
            "role": "assistant",
            "content": "We offer Short Cut and Long Cut — which service with Jake?",
        },
        {"role": "user", "content": "yes long cut"},
    ]
    assert service_choice_resolved(history, ctx, canonical_service="Long Cut")


def test_user_affirmed_after_service_prompt():
    ctx = _ctx()
    history = [
        {"role": "assistant", "content": "Which service would you like? Short Cut or Long Cut."},
        {"role": "user", "content": "yeah long cut"},
    ]
    assert user_affirmed_after_service_prompt(history, ctx)


def test_service_prompt_repeat_wording():
    first = service_prompt_message(
        staff_name="Jake", service_choices="Short Cut, Long Cut", already_asked=False
    )
    repeat = service_prompt_message(
        staff_name="Jake", service_choices="Short Cut, Long Cut", already_asked=True
    )
    assert "Just to confirm" not in first
    assert "Just to confirm" not in repeat
    assert "still need the service" in repeat.lower()
    assert "which service" in first.lower()
