"""send_sms routes through the A2P Messaging Service when configured.

Sending booking confirmations from a raw long code that isn't in a registered
Messaging Service gets carrier error 30034 ("unregistered number") and is dropped.
Routing via the Messaging Service SID makes every message inherit the approved
10DLC campaign. These tests pin that routing.
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


def test_sends_via_messaging_service_when_env_set(mock_twilio, monkeypatch):
    monkeypatch.setenv("TWILIO_A2P_MESSAGING_SERVICE_SID", "MGabc123")
    ok = sms_service.send_sms("+14255551234", "hi", from_override="+14782150212")
    assert ok is True
    kwargs = mock_twilio.messages.create.call_args.kwargs
    assert kwargs.get("messaging_service_sid") == "MGabc123"
    # The service selects the From from its pool — a raw From must NOT be passed.
    assert "from_" not in kwargs
    assert kwargs.get("to") == "+14255551234"


def test_falls_back_to_from_number_without_service(mock_twilio, monkeypatch):
    monkeypatch.delenv("TWILIO_A2P_MESSAGING_SERVICE_SID", raising=False)
    ok = sms_service.send_sms("+14255551234", "hi", from_override="+14782150212")
    assert ok is True
    kwargs = mock_twilio.messages.create.call_args.kwargs
    assert kwargs.get("from_") == "+14782150212"
    assert "messaging_service_sid" not in kwargs


def test_param_overrides_env(mock_twilio, monkeypatch):
    monkeypatch.setenv("TWILIO_A2P_MESSAGING_SERVICE_SID", "MGenv")
    ok = sms_service.send_sms("+14255551234", "hi", messaging_service_sid="MGparam")
    assert ok is True
    kwargs = mock_twilio.messages.create.call_args.kwargs
    assert kwargs.get("messaging_service_sid") == "MGparam"


def test_skips_when_no_service_and_no_from(mock_twilio, monkeypatch):
    monkeypatch.delenv("TWILIO_A2P_MESSAGING_SERVICE_SID", raising=False)
    monkeypatch.setattr(sms_service, "TWILIO_SMS_FROM", "")
    ok = sms_service.send_sms("+14255551234", "hi")
    assert ok is False
    mock_twilio.messages.create.assert_not_called()
