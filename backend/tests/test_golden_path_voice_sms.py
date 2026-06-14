"""Golden-path voice → booking → SMS contract tests (mocked externals)."""
from __future__ import annotations

from unittest.mock import MagicMock

import main
from routers import phone as phone_router
import database
import conversation_service
import config_service
import sms_service


def test_no_transfer_number_speaks_honest_fallback(monkeypatch):
    """Caller asked for a human (forward_unavailable flagged) but no forwarding number is
    configured → the AI must speak the honest take-a-message line, never pretend to be human."""
    import asyncio
    import runtime

    monkeypatch.setattr(config_service, "get_business_info",
                        lambda: {"name": "Test Cuts", "forwarding_phone": "", "staff": [], "services": []})
    monkeypatch.setattr(config_service, "staff_roster_ready_for_booking", lambda info=None: False)
    # GPT tries to claim it's a person — the override must replace this.
    monkeypatch.setattr(main.client.chat.completions, "create", MagicMock())
    main.client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="I'm a real person, here to help you!"))]
    )

    call_sid = "CAhonestfallbackaaaaaaaaaaaaaaaaaa"
    call_data = {
        "client_id": "test-cuts",
        "from_number": "+15551230000",
        "to_number": "+15559876543",
        "conversation_history": [{"role": "user", "content": "can I talk to a real person"}],
        "forward_unavailable": True,
    }
    asyncio.run(main.generate_response_async(call_sid, call_data, "English", "https://api.example.com"))
    status = runtime.call_store.response_status.get(call_sid, {})
    assert status.get("status") == "ready"
    assert "AI receptionist" in (status.get("ai_text") or "")
    assert "real person" not in (status.get("ai_text") or "").lower()


def test_generate_response_async_links_sms_session_on_booking(monkeypatch):
    """Happy path: BOOKING line creates appointment and links SMS session."""
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
            "id": 99,
            "name": "Alex",
            "date": future_date,
            "time": "15:00",
            "phone": "+15551234567",
            "status": "pending_customer",
        },
    )
    monkeypatch.setattr(sms_service, "send_sms", lambda *a, **k: True)
    monkeypatch.setattr(
        database,
        "db_sms_session_upsert",
        lambda phone, cid, messages, appointment_id=None: linked.append(appointment_id),
    )
    monkeypatch.setattr(main.client.chat.completions, "create", MagicMock())
    main.client.chat.completions.create.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content=f"BOOKING: Alex|+15551234567||{future_date}|15:00|Haircut|"
                )
            )
        ]
    )

    from voice.call_sid import SAMPLE_CALL_SID

    call_sid = SAMPLE_CALL_SID
    call_data = {
        "client_id": "salon-test",
        "from_number": "+15551234567",
        "to_number": "+15559876543",
        "conversation_history": [{"role": "user", "content": "book a haircut tomorrow at 3"}],
    }
    main.active_calls[call_sid] = call_data
    import asyncio

    asyncio.run(main.generate_response_async(call_sid, call_data, "English", "https://api.example.com"))
    assert linked == [99]
    assert main.response_status.get(call_sid, {}).get("status") in ("ready", "pending", "forward")


def test_incoming_call_resolves_tenant_by_to_number(monkeypatch):
    """Contract: incoming handler uses db_tenant_get_by_phone for tenant resolution."""
    import inspect

    source = inspect.getsource(phone_router.handle_incoming_call)
    assert "db_tenant_get_by_phone" in source
    assert "tenant_resolved_by_to_number" in source or "tenant_not_resolved" in source


def test_cleanup_clears_response_status():
    """Runtime cleanup must clear response polling state."""
    sid = "CAdddddddddddddddddddddddddddddddd"
    main.active_calls[sid] = {"client_id": "t1"}
    main.response_status[sid] = {"status": "pending"}
    main.cleanup_call_runtime_state(sid)
    assert sid not in main.active_calls
    assert sid not in main.response_status
