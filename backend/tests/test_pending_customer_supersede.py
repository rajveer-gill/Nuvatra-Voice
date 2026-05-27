"""Unconfirmed voice drafts must not block rebooking the same slot."""

from __future__ import annotations

from unittest.mock import patch

import main


def test_supersede_cancels_pending_customer_same_slot():
    rows = [
        {
            "id": 9,
            "date": "2026-06-01",
            "time": "14:00",
            "status": "pending_customer",
            "phone": "+15551110000",
            "staff_id": None,
        }
    ]
    updated = []

    with patch.object(main, "USE_DB", True), patch.object(
        main, "_appointment_rows_for_calendar_merge", return_value=rows
    ), patch.object(main, "db_appointments_update", side_effect=lambda aid, **kw: updated.append((aid, kw))), patch.object(
        main, "release_slot"
    ), patch.object(main, "get_db_client_id", return_value="test"):
        n = main._supersede_pending_customer_drafts_for_slot(
            "2026-06-01",
            "14:00",
            None,
            client_id="test",
            phone="+15551110000",
        )
    assert n == 1
    assert updated[0][0] == 9
    assert updated[0][1]["status"] == "cancelled"


def test_supersede_skips_pending_review():
    rows = [
        {
            "id": 10,
            "date": "2026-06-01",
            "time": "14:00",
            "status": "pending_review",
            "phone": "+15551110000",
            "staff_id": None,
        }
    ]
    with patch.object(main, "USE_DB", True), patch.object(
        main, "_appointment_rows_for_calendar_merge", return_value=rows
    ), patch.object(main, "db_appointments_update") as upd:
        n = main._supersede_pending_customer_drafts_for_slot(
            "2026-06-01",
            "14:00",
            None,
            client_id="test",
            phone="+15551110000",
        )
    assert n == 0
    upd.assert_not_called()
