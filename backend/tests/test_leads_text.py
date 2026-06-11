"""Lead follow-up texting: POST /api/leads/{id}/text.

Plan-gated (Growth/Pro), tenant-scoped, and surfaces SMS send failures the same
way the appointment/message flows do.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import booking_service
import database
import deps
import sms_service
from routers import leads


def _wire(monkeypatch, *, lead, send_result=True, has_lead_capture=True):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: "test")
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(leads, "get_plan_limits", lambda tenant: {"has_lead_capture": has_lead_capture})
    monkeypatch.setattr(database, "db_leads_get_by_id", lambda lid, cid: dict(lead) if lead and lid == lead["id"] else None)
    monkeypatch.setattr(booking_service, "_tenant_sms_from_number", lambda: "+15552220000")
    sent = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, body, from_override=None: sent.append((to, body)) or send_result)
    return sent


def test_text_lead_sends(monkeypatch):
    sent = _wire(monkeypatch, lead={"id": 4, "phone": "+15551110000"})
    result = leads.text_lead(
        4, leads.LeadTextBody(text="Want to book a time?"), request=MagicMock(), tenant={"client_id": "test"}
    )
    assert result["text_sms_sent"] is True
    assert sent == [("+15551110000", "Want to book a time?")]


def test_text_lead_surfaces_failure(monkeypatch):
    _wire(monkeypatch, lead={"id": 4, "phone": "+15551110000"}, send_result=False)
    result = leads.text_lead(
        4, leads.LeadTextBody(text="hi"), request=MagicMock(), tenant={"client_id": "test"}
    )
    assert result["text_sms_sent"] is False


def test_text_lead_404(monkeypatch):
    _wire(monkeypatch, lead=None)
    with pytest.raises(HTTPException) as exc:
        leads.text_lead(9, leads.LeadTextBody(text="hi"), request=MagicMock(), tenant={"client_id": "test"})
    assert exc.value.status_code == 404


def test_text_lead_400_no_phone(monkeypatch):
    _wire(monkeypatch, lead={"id": 4, "phone": ""})
    with pytest.raises(HTTPException) as exc:
        leads.text_lead(4, leads.LeadTextBody(text="hi"), request=MagicMock(), tenant={"client_id": "test"})
    assert exc.value.status_code == 400


def test_text_lead_403_when_plan_lacks_capability(monkeypatch):
    _wire(monkeypatch, lead={"id": 4, "phone": "+15551110000"}, has_lead_capture=False)
    with pytest.raises(HTTPException) as exc:
        leads.text_lead(4, leads.LeadTextBody(text="hi"), request=MagicMock(), tenant={"client_id": "test"})
    assert exc.value.status_code == 403
