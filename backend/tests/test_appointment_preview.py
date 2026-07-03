"""Decline/cancel SMS preview endpoint accepts the dashboard's action names."""

from unittest.mock import MagicMock

import booking_service
import config_service
import deps
from routers import appointments as appts


def _wire(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", False)
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: "test")
    monkeypatch.setattr(config_service, "get_business_info", lambda: {"name": "Test Cuts"})
    captured = {}

    def _fake_polish(reason, business_name, apt, *, event="decline"):
        captured["event"] = event
        return f"polished: {reason}"

    monkeypatch.setattr(booking_service, "polish_owner_customer_sms", _fake_polish)
    return captured


def test_preview_accepts_reject_event_and_maps_to_decline(monkeypatch):
    # Regression: the dashboard sends event="reject"; a Literal["decline","cancel"] used to 422
    # it, so the owner saw "Could not generate preview".
    captured = _wire(monkeypatch)
    body = appts.PreviewDeclineSmsBody(reason="store closed", event="reject")
    out = appts.preview_decline_sms(body, tenant={"client_id": "test"})
    assert out["polished_message"] == "polished: store closed"
    assert captured["event"] == "decline"  # reject normalized to decline


def test_preview_accepts_cancel_event(monkeypatch):
    captured = _wire(monkeypatch)
    body = appts.PreviewDeclineSmsBody(reason="closing early", event="cancel")
    out = appts.preview_decline_sms(body, tenant={"client_id": "test"})
    assert out["polished_message"] == "polished: closing early"
    assert captured["event"] == "cancel"
