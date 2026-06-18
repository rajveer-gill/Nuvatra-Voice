"""Tests for the 'text the customer their car is ready' action (auto body)."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import booking_service
import config_service
import database
import deps
import sms_service
from routers import appointments as appts


def _common(monkeypatch, sent):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(config_service, "get_business_info", lambda: {"name": "Summit Collision"})
    monkeypatch.setattr(
        sms_service, "send_sms",
        lambda to, body, from_override=None: sent.append((to, body)) or True,
    )
    monkeypatch.setattr(booking_service, "_tenant_sms_from_number", lambda: "+15552220000")
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: "test")
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)


def test_notify_ready_texts_customer_and_records(monkeypatch):
    sent = []
    _common(monkeypatch, sent)
    stored = {
        "id": 5, "status": "accepted", "name": "Casey", "phone": "+15551110000",
        "date": "2026-07-01", "intake": {"vehicle": "2019 Honda Civic"}, "ready_notified_at": None,
    }
    monkeypatch.setattr(database, "db_appointments_get_by_id", lambda aid, client_id=None: dict(stored) if aid == 5 else None)

    def fake_update(aid, client_id=None, **kw):
        stored.update(kw)
        return dict(stored)

    monkeypatch.setattr(database, "db_appointments_update", fake_update)

    res = appts.notify_ready(5, request=MagicMock(), tenant={"client_id": "test"})
    assert res["success"] is True
    assert res["ready_notified_at"]
    # Idempotency timestamp was recorded.
    assert stored.get("ready_notified_at") is not None
    # Texted the on-file number, message names the vehicle + business.
    to, body = sent[0]
    assert to == "+15551110000"
    assert "2019 Honda Civic" in body and "Summit Collision" in body


def test_notify_ready_is_idempotent(monkeypatch):
    sent = []
    _common(monkeypatch, sent)
    monkeypatch.setattr(
        database, "db_appointments_get_by_id",
        lambda aid, client_id=None: {"id": 5, "phone": "+15551110000", "ready_notified_at": "2026-07-01T10:00:00Z"},
    )
    with pytest.raises(HTTPException) as exc:
        appts.notify_ready(5, request=MagicMock(), tenant={"client_id": "test"})
    assert exc.value.status_code == 409
    assert not sent  # never re-texts


def test_notify_ready_requires_phone(monkeypatch):
    sent = []
    _common(monkeypatch, sent)
    monkeypatch.setattr(
        database, "db_appointments_get_by_id",
        lambda aid, client_id=None: {"id": 5, "phone": "", "ready_notified_at": None},
    )
    with pytest.raises(HTTPException) as exc:
        appts.notify_ready(5, request=MagicMock(), tenant={"client_id": "test"})
    assert exc.value.status_code == 400
    assert not sent


def test_notify_ready_send_failure_does_not_record(monkeypatch):
    """If the text fails, ready_notified_at must NOT be set, so the shop can retry."""
    sent = []
    _common(monkeypatch, sent)
    monkeypatch.setattr(sms_service, "send_sms", lambda to, body, from_override=None: False)
    updated = {}
    monkeypatch.setattr(
        database, "db_appointments_get_by_id",
        lambda aid, client_id=None: {"id": 5, "phone": "+15551110000", "ready_notified_at": None, "name": "Casey"},
    )
    monkeypatch.setattr(database, "db_appointments_update", lambda aid, client_id=None, **kw: updated.update(kw) or {})
    with pytest.raises(HTTPException) as exc:
        appts.notify_ready(5, request=MagicMock(), tenant={"client_id": "test"})
    assert exc.value.status_code == 502
    assert "ready_notified_at" not in updated  # not recorded on failure
