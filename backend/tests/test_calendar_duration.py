"""Calendar event duration from booked_slots and service menu."""
import main


def test_duration_from_booked_slot():
    apt = {"id": 42, "reason": "Short Cut"}
    slots = {42: 30}
    assert main._duration_minutes_for_appointment(apt, slots, []) == 30


def test_duration_from_service_name_when_no_slot():
    apt = {"id": 1, "reason": "Short Cut"}
    services = [{"name": "Short Cut", "duration_minutes": 30}]
    assert main._duration_minutes_for_appointment(apt, {}, services) == 30


def test_duration_default_when_unknown():
    apt = {"id": 1, "reason": "Walk-in"}
    assert main._duration_minutes_for_appointment(apt, {}, []) == main.DEFAULT_SLOT_DURATION_MINUTES
