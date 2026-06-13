"""SMS appointment resolution for voice-booking confirm flow."""

from __future__ import annotations

from unittest.mock import MagicMock

import main
import database
import conversation_service
import config_service
import sms_service


def test_inbound_sms_uses_resolve_not_phone_only(monkeypatch):
    """Inbound handler must resolve appointment via phone + session fallback."""
    import inspect

    source = inspect.getsource(main.handle_incoming_sms)
    assert "db_appointments_resolve_for_sms" in source
    assert "db_appointments_get_by_phone_for_sms(from_number)" not in source


def test_post_booking_links_sms_session(monkeypatch):
    """After confirmation SMS, voice flow should link sms_sessions to appointment id."""
    from datetime import timedelta
    import business_hours

    # Future date so booking validation (which now rejects past dates) accepts it.
    future_date = (business_hours.business_local_now({}) + timedelta(days=5)).date().isoformat()
    linked = []

    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(config_service, "staff_roster_ready_for_booking", lambda info=None: True)
    monkeypatch.setattr(
        conversation_service,
        "_create_appointment_from_booking",
        lambda booking, client_id_override=None, reserve_slot_immediately=True, **kwargs: {
            "id": 42,
            "name": "Pat",
            "date": future_date,
            "time": "14:00",
            "phone": "+15551110000",
        },
    )
    monkeypatch.setattr(sms_service, "send_sms", lambda *a, **k: True)
    monkeypatch.setattr(
        database,
        "db_sms_session_upsert",
        lambda phone, cid, messages, appointment_id=None: linked.append(
            (phone, cid, appointment_id)
        ),
    )
    monkeypatch.setattr(main.client.chat.completions, "create", MagicMock())
    main.client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=f"BOOKING: Pat|+15551110000||{future_date}|14:00|Cut|"))]
    )

    call_sid = "CAeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    call_data = {
        "client_id": "test",
        "from_number": "+15551110000",
        "to_number": "+15552220000",
        "conversation_history": [{"role": "user", "content": "book me"}],
    }
    main.response_status[call_sid] = {}
    import asyncio

    asyncio.run(
        main.generate_response_async(call_sid, call_data, "English", "https://api.example.com")
    )
    assert linked and linked[0][2] == 42
