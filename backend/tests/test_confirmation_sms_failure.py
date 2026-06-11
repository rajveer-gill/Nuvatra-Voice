"""Dashboard accept/decline/cancel must not silently swallow a failed confirmation text.

When sms_service.send_sms returns False, the route should flag the appointment
(confirmation_sms_failed) and report confirmation_sms_sent=False so the dashboard
can tell the business to call the customer. Helpers resolve by module, so patches
target the owning modules (database / booking_service / config_service / sms_service).
"""

from unittest.mock import MagicMock

import booking_service
import config_service
import database
import deps
import sms_service
from routers import appointments as appts


def _wire_common(monkeypatch, stored, send_result):
    sent_bodies = []

    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(
        database,
        "db_appointments_get_by_id",
        lambda aid, client_id=None: dict(stored) if aid == stored["id"] else None,
    )

    def fake_update(aid, client_id=None, **kwargs):
        stored.update(kwargs)
        return dict(stored)

    monkeypatch.setattr(database, "db_appointments_update", fake_update)
    monkeypatch.setattr(booking_service, "release_slot", lambda aid: None)
    monkeypatch.setattr(config_service, "get_business_info", lambda: {"name": "Test Biz"})
    monkeypatch.setattr(booking_service, "_hhmm_to_ampm", lambda t: "2:00 PM")
    monkeypatch.setattr(
        booking_service, "polish_owner_decline_sms", lambda reason, biz, apt: "declined"
    )
    monkeypatch.setattr(
        booking_service,
        "polish_owner_customer_sms",
        lambda reason, biz, apt, event="decline": "cancelled",
    )
    monkeypatch.setattr(
        sms_service,
        "send_sms",
        lambda to, body, from_override=None: sent_bodies.append(body) or send_result,
    )
    monkeypatch.setattr(booking_service, "_tenant_sms_from_number", lambda: "+15552220000")
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: "test")
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(appts, "system_info", lambda *a, **k: None)
    return sent_bodies


def test_accept_flags_when_confirmation_text_fails(monkeypatch):
    stored = {
        "id": 11,
        "status": "pending_review",
        "name": "Jake",
        "phone": "+15551110000",
        "date": "2026-05-28",
        "time": "14:00",
    }
    _wire_common(monkeypatch, stored, send_result=False)

    result = appts.accept_appointment(11, request=MagicMock(), tenant={"client_id": "test"})

    assert result["success"] is True
    assert result["confirmation_sms_sent"] is False
    assert result["appointment"]["confirmation_sms_failed"] is True
    # Status still advanced — a transient SMS hiccup must not block accepting.
    assert stored["status"] == "accepted"
    assert stored["confirmation_sms_failed"] is True


def test_accept_clean_when_confirmation_text_sends(monkeypatch):
    stored = {
        "id": 12,
        "status": "pending_review",
        "name": "Ana",
        "phone": "+15551110001",
        "date": "2026-05-28",
        "time": "15:00",
    }
    _wire_common(monkeypatch, stored, send_result=True)

    result = appts.accept_appointment(12, request=MagicMock(), tenant={"client_id": "test"})

    assert result["confirmation_sms_sent"] is True
    assert result["appointment"].get("confirmation_sms_failed") in (False, None)
    assert "confirmation_sms_failed" not in stored  # never written on success


def test_cancel_flags_when_text_fails(monkeypatch):
    stored = {
        "id": 13,
        "status": "accepted",
        "name": "Lee",
        "phone": "+15551110002",
        "date": "2026-05-28",
        "time": "16:00",
    }
    _wire_common(monkeypatch, stored, send_result=False)

    result = appts.cancel_appointment(
        13,
        appts.AppointmentRejectBody(reason="closing early"),
        request=MagicMock(),
        tenant={"client_id": "test"},
    )

    assert result["confirmation_sms_sent"] is False
    assert result["appointment"]["confirmation_sms_failed"] is True
    assert stored["status"] == "cancelled"


def test_consent_record_is_graceful_without_db(monkeypatch):
    # No DB connection (unit run): must return quietly, never raise into a webhook.
    monkeypatch.setattr(database, "_get_conn", lambda: None)
    database.db_sms_consent_record("+15551110000", "test", "inbound_sms")
