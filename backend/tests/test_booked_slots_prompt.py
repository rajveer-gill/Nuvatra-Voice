"""Booked-slot prompt text must be per-stylist for multi-staff salons."""

from datetime import datetime, timezone
from unittest.mock import patch

import main


def test_multi_staff_prompt_keeps_stylist_availability_separate(monkeypatch):
    tomorrow = "2026-06-05"
    monkeypatch.setattr(main, "get_db_client_id", lambda: "salon-test")
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {
            "staff": [
                {"id": "jake-id", "name": "Jake"},
                {"id": "sara-id", "name": "Sarah"},
            ]
        },
    )
    slots = [
        {"date": tomorrow, "time": "09:00", "staff_id": "sara-id"},
        {"date": tomorrow, "time": "10:00", "staff_id": "sara-id"},
        {"date": tomorrow, "time": "11:00", "staff_id": "sara-id"},
        {"date": tomorrow, "time": "13:00", "staff_id": "sara-id"},
        {"date": tomorrow, "time": "14:00", "staff_id": "sara-id"},
        {"date": tomorrow, "time": "15:00", "staff_id": "sara-id"},
        {"date": tomorrow, "time": "16:00", "staff_id": "sara-id"},
        {"date": tomorrow, "time": "17:00", "staff_id": "sara-id"},
    ]
    with patch("main._get_all_booked_slots_merged", return_value=slots), patch(
        "main.datetime"
    ) as dt_mod:
        dt_mod.now.return_value = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        main._invalidate_booked_slots_cache()
        text = main.get_booked_slots_prompt_text(days_ahead=2, skip_cache=True)

    assert "by stylist" in text.lower()
    assert "Sarah" in text
    assert f"For Jake on {tomorrow} no times are booked for Jake" in text
    assert "fully booked for Jake" not in text
    assert "For Sarah on" in text


def test_single_staff_prompt_unchanged_shape(monkeypatch):
    monkeypatch.setattr(main, "get_db_client_id", lambda: "solo")
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {"staff": [{"id": "solo-id", "name": "Jamie"}]},
    )
    slots = [{"date": "2026-06-05", "time": "14:00", "staff_id": "solo-id"}]
    with patch("main._get_all_booked_slots_merged", return_value=slots), patch(
        "main.datetime"
    ) as dt_mod:
        dt_mod.now.return_value = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        main._invalidate_booked_slots_cache()
        text = main.get_booked_slots_prompt_text(days_ahead=2, skip_cache=True)

    assert "Booked slots (do not double-book)" in text
    assert "For 2026-06-05 ONLY suggest these times" in text
    assert "by stylist" not in text.lower()
