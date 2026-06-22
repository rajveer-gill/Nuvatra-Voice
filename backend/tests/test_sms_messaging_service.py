"""send_sms routing: prefer the tenant's own number (so two-way replies resolve to
the tenant), fall back to the A2P Messaging Service only when no From is available.

The tenant number must be enrolled in the Messaging Service so it inherits the 10DLC
campaign (else carrier error 30034). Sending via the Messaging Service SID would send
from a pooled number, which breaks reply→tenant mapping — so it is fallback-only.
"""

from unittest.mock import MagicMock

import pytest

import runtime
import sms_service


@pytest.fixture
def mock_twilio(monkeypatch):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(sid="SMtest123")
    monkeypatch.setattr(runtime, "twilio_client", client)
    monkeypatch.setattr(runtime, "USE_DB", False)
    monkeypatch.setattr(sms_service.deps, "audit_log", lambda *a, **k: None)
    return client


def test_prefers_tenant_from_number_even_when_service_set(mock_twilio, monkeypatch):
    # Two-way replies must come back to the tenant's own number, so a real From
    # always wins over the Messaging Service (the number is enrolled for A2P).
    monkeypatch.setenv("TWILIO_A2P_MESSAGING_SERVICE_SID", "MGabc123")
    ok = sms_service.send_sms("+14255551234", "hi", from_override="+14782150212")
    assert ok is True
    kwargs = mock_twilio.messages.create.call_args.kwargs
    assert kwargs.get("from_") == "+14782150212"
    assert "messaging_service_sid" not in kwargs
    assert kwargs.get("to") == "+14255551234"


def test_uses_from_number_without_service(mock_twilio, monkeypatch):
    monkeypatch.delenv("TWILIO_A2P_MESSAGING_SERVICE_SID", raising=False)
    ok = sms_service.send_sms("+14255551234", "hi", from_override="+14782150212")
    assert ok is True
    kwargs = mock_twilio.messages.create.call_args.kwargs
    assert kwargs.get("from_") == "+14782150212"
    assert "messaging_service_sid" not in kwargs


def test_falls_back_to_messaging_service_when_no_from(mock_twilio, monkeypatch):
    # Only when there is no From at all do we route via the Messaging Service.
    monkeypatch.setenv("TWILIO_A2P_MESSAGING_SERVICE_SID", "MGfallback")
    monkeypatch.setattr(sms_service, "TWILIO_SMS_FROM", "")
    ok = sms_service.send_sms("+14255551234", "hi")
    assert ok is True
    kwargs = mock_twilio.messages.create.call_args.kwargs
    assert kwargs.get("messaging_service_sid") == "MGfallback"
    assert "from_" not in kwargs


def test_skips_when_no_service_and_no_from(mock_twilio, monkeypatch):
    monkeypatch.delenv("TWILIO_A2P_MESSAGING_SERVICE_SID", raising=False)
    monkeypatch.setattr(sms_service, "TWILIO_SMS_FROM", "")
    ok = sms_service.send_sms("+14255551234", "hi")
    assert ok is False
    mock_twilio.messages.create.assert_not_called()
