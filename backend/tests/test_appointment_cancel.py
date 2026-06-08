"""Tests for store cancellation of accepted appointments."""

from unittest.mock import MagicMock

import main


def test_cancel_accepted_appointment(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    stored = {
        "id": 7,
        "status": "accepted",
        "name": "Jake",
        "phone": "+15551110000",
        "date": "2026-05-28",
        "time": "14:00",
    }
    released = []
    sent = []

    monkeypatch.setattr(
        main,
        "db_appointments_get_by_id",
        lambda aid, client_id=None: dict(stored) if aid == 7 else None,
    )

    def fake_update(aid, client_id=None, **kwargs):
        stored.update(kwargs)
        return dict(stored)

    monkeypatch.setattr(main, "db_appointments_update", fake_update)
    monkeypatch.setattr(main, "release_slot", lambda aid: released.append(aid))
    monkeypatch.setattr(main, "get_business_info", lambda: {"name": "Test Biz"})
    monkeypatch.setattr(
        main,
        "polish_owner_customer_sms",
        lambda reason, biz, apt, event="decline": f"cancel:{event}",
    )
    monkeypatch.setattr(
        main,
        "send_sms",
        lambda to, body, from_override=None: sent.append(body) or True,
    )
    monkeypatch.setattr(main, "_tenant_sms_from_number", lambda: "+15552220000")
    monkeypatch.setattr(main, "_bind_tenant_db_context", lambda tenant: "test")
    monkeypatch.setattr(main, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(main, "system_info", lambda *a, **k: None)

    import asyncio

    result = asyncio.run(
        main.cancel_appointment(
            7,
            main.AppointmentRejectBody(reason="Clearing test booking"),
            request=MagicMock(),
            tenant={"client_id": "test"},
        )
    )
    assert result["success"] is True
    assert stored["status"] == "cancelled"
    assert released == [7]
    assert sent and sent[0] == "cancel:cancel"


def test_cancel_rejects_pending_review(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(
        main,
        "db_appointments_get_by_id",
        lambda aid, client_id=None: {"id": 1, "status": "pending_review"},
    )
    monkeypatch.setattr(main, "_bind_tenant_db_context", lambda tenant: "test")

    import asyncio
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            main.cancel_appointment(
                1,
                main.AppointmentRejectBody(reason="nope"),
                request=MagicMock(),
                tenant={"client_id": "test"},
            )
        )
    assert exc.value.status_code == 400
