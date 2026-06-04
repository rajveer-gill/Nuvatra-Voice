"""Calendar event duration from booked_slots and service menu."""
import main


def test_duration_from_booked_slot_when_no_service_match():
    apt = {"id": 42, "reason": "Walk-in"}
    slots = {42: 45}
    assert main._duration_minutes_for_appointment(apt, slots, []) == 45


def test_duration_prefers_service_over_stale_booked_slot():
    apt = {"id": 42, "reason": "Long Cut"}
    slots = {42: 30}
    services = [{"name": "Long Cut", "duration_minutes": 45}]
    assert main._duration_minutes_for_appointment(apt, slots, services) == 45


def test_duration_from_service_name_when_no_slot():
    apt = {"id": 1, "reason": "Short Cut"}
    services = [{"name": "Short Cut", "duration_minutes": 30}]
    assert main._duration_minutes_for_appointment(apt, {}, services) == 30


def test_duration_default_when_unknown():
    apt = {"id": 1, "reason": "Walk-in"}
    assert main._duration_minutes_for_appointment(apt, {}, []) == main.DEFAULT_SLOT_DURATION_MINUTES


def test_booking_duration_from_service_menu(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {
            "services": [{"name": "Long Cut", "duration_minutes": 45}],
        },
    )
    assert (
        main._booking_duration_minutes({"reason": "Long Cut"})
        == 45
    )
