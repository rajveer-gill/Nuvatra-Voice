"""booked_slots rows must not block the calendar unless the appointment still holds the slot."""
from unittest.mock import patch

from main import _booked_slot_rows_that_hold_calendar, is_slot_available, _invalidate_booked_slots_cache


def test_booked_slot_pending_customer_ignored():
    raw = [
        {
            "date": "2026-07-01",
            "time": "14:00",
            "appointment_id": 42,
            "duration_minutes": 30,
            "staff_id": None,
        }
    ]
    apt_by_id = {
        42: {
            "id": 42,
            "date": "2026-07-01",
            "time": "14:00",
            "status": "pending_customer",
            "staff_id": None,
        }
    }
    assert _booked_slot_rows_that_hold_calendar(raw, apt_by_id) == []


def test_booked_slot_pending_review_kept():
    raw = [
        {
            "date": "2026-07-02",
            "time": "10:00",
            "appointment_id": 7,
            "duration_minutes": 30,
            "staff_id": None,
        }
    ]
    apt_by_id = {
        7: {
            "id": 7,
            "date": "2026-07-02",
            "time": "10:00",
            "status": "pending_review",
            "staff_id": None,
        }
    }
    assert len(_booked_slot_rows_that_hold_calendar(raw, apt_by_id)) == 1


def test_is_slot_available_ignores_stale_row_for_pending_customer():
    with patch("main._load_booked_slots") as load, patch("main.USE_DB", True), patch(
        "main.db_appointments_get_all"
    ) as ga:
        load.return_value = [
            {
                "date": "2026-08-10",
                "time": "15:00",
                "appointment_id": 99,
                "duration_minutes": 30,
                "staff_id": None,
            }
        ]
        ga.return_value = [
            {
                "id": 99,
                "date": "2026-08-10",
                "time": "15:00",
                "status": "pending_customer",
                "staff_id": None,
            }
        ]
        _invalidate_booked_slots_cache()
        assert is_slot_available("2026-08-10", "15:00", 30, None) is True


def test_is_slot_available_orphan_booked_slot_ignored():
    with patch("main._load_booked_slots") as load, patch("main.USE_DB", True), patch(
        "main.db_appointments_get_all"
    ) as ga:
        load.return_value = [
            {
                "date": "2026-08-11",
                "time": "11:00",
                "appointment_id": 404,
                "duration_minutes": 30,
                "staff_id": None,
            }
        ]
        ga.return_value = []
        _invalidate_booked_slots_cache()
        assert is_slot_available("2026-08-11", "11:00", 30, None) is True
