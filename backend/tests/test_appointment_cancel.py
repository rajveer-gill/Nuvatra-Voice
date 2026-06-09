"""Tests for store cancellation of accepted appointments.

cancel_appointment now lives in routers/appointments.py and resolves its helpers by
module (database / booking_service / config_service / sms_service / deps), so patches
target those owning modules rather than `main`.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import booking_service
import config_service
import database
import deps
import sms_service
from routers import appointments as appts


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
        database,
        "db_appointments_get_by_id",
        lambda aid, client_id=None: dict(stored) if aid == 7 else None,
    )

    def fake_update(aid, client_id=None, **kwargs):
        stored.update(kwargs)
        return dict(stored)

    monkeypatch.setattr(database, "db_appointments_update", fake_update)
    monkeypatch.setattr(booking_service, "release_slot", lambda aid: released.append(aid))
    monkeypatch.setattr(config_service, "get_business_info", lambda: {"name": "Test Biz"})
    monkeypatch.setattr(
        booking_service,
        "polish_owner_customer_sms",
        lambda reason, biz, apt, event="decline": f"cancel:{event}",
    )
    monkeypatch.setattr(
        sms_service,
        "send_sms",
        lambda to, body, from_override=None: sent.append(body) or True,
    )
    monkeypatch.setattr(booking_service, "_tenant_sms_from_number", lambda: "+15552220000")
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: "test")
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(appts, "system_info", lambda *a, **k: None)

    result = asyncio.run(
        appts.cancel_appointment(
            7,
            appts.AppointmentRejectBody(reason="Clearing test booking"),
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
        database,
        "db_appointments_get_by_id",
        lambda aid, client_id=None: {"id": 1, "status": "pending_review"},
    )
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: "test")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            appts.cancel_appointment(
                1,
                appts.AppointmentRejectBody(reason="nope"),
                request=MagicMock(),
                tenant={"client_id": "test"},
            )
        )
    assert exc.value.status_code == 400
