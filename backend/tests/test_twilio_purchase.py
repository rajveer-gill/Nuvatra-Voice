"""Twilio number auto-purchase for bulk onboarding."""

from __future__ import annotations

from unittest.mock import MagicMock

import twilio_provision


class _FakeNumber:
    def __init__(self, phone, sid):
        self.phone_number = phone
        self.sid = sid


def _fake_client(available_numbers, created):
    client = MagicMock()
    client.available_phone_numbers.return_value.local.list.return_value = available_numbers
    client.incoming_phone_numbers.create.return_value = created
    return client


BASE = "https://api.example.com"


def test_purchase_success_configures_webhooks(monkeypatch):
    created = _FakeNumber("+15551230001", "PNxxxx")
    client = _fake_client([_FakeNumber("+15551230001", None)], created)
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda sid, tok: client)

    out = twilio_provision.purchase_number(
        account_sid="AC", auth_token="tok", base_url=BASE, area_code="555"
    )
    assert out["ok"] is True
    assert out["phone_e164"] == "+15551230001"
    assert out["number_sid"] == "PNxxxx"
    assert out["errors"] == []
    # bought with webhook URLs set at creation time
    kwargs = client.incoming_phone_numbers.create.call_args.kwargs
    assert kwargs["voice_url"].endswith("/api/phone/incoming")
    assert kwargs["sms_url"].endswith("/api/sms/incoming")
    assert kwargs["status_callback"].endswith("/api/phone/status")


def test_purchase_no_numbers_available(monkeypatch):
    client = _fake_client([], None)
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda sid, tok: client)
    out = twilio_provision.purchase_number(account_sid="AC", auth_token="tok", base_url=BASE)
    assert out["ok"] is False
    assert "no_available_numbers" in out["errors"]
    client.incoming_phone_numbers.create.assert_not_called()


def test_purchase_requires_credentials():
    out = twilio_provision.purchase_number(account_sid="", auth_token="", base_url=BASE)
    assert out["ok"] is False
    assert "twilio_credentials_required" in out["errors"]


def test_purchase_rejects_bad_base_url():
    out = twilio_provision.purchase_number(account_sid="AC", auth_token="tok", base_url="http://insecure")
    assert out["ok"] is False
    assert any("public_base_url" in e for e in out["errors"])


def test_purchase_handles_twilio_exception(monkeypatch):
    client = MagicMock()
    client.available_phone_numbers.return_value.local.list.side_effect = RuntimeError("boom")
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda sid, tok: client)
    out = twilio_provision.purchase_number(account_sid="AC", auth_token="tok", base_url=BASE)
    assert out["ok"] is False
    assert "twilio_purchase_failed" in out["errors"]


# --- A2P Messaging Service enrollment -----------------------------------------

def test_purchase_enrolls_number_in_messaging_service(monkeypatch):
    monkeypatch.setenv("TWILIO_A2P_MESSAGING_SERVICE_SID", "MG123")
    client = _fake_client([_FakeNumber("+15551230001", None)], _FakeNumber("+15551230001", "PNxxxx"))
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda sid, tok: client)

    out = twilio_provision.purchase_number(account_sid="AC", auth_token="tok", base_url=BASE)
    assert out["ok"] is True
    assert out["messaging_service_enrolled"] is True
    assert out["errors"] == []
    client.messaging.v1.services.assert_called_with("MG123")
    enroll_kwargs = client.messaging.v1.services.return_value.phone_numbers.create.call_args.kwargs
    assert enroll_kwargs["phone_number_sid"] == "PNxxxx"


def test_purchase_enroll_idempotent_when_already_present(monkeypatch):
    monkeypatch.setenv("TWILIO_A2P_MESSAGING_SERVICE_SID", "MG123")
    client = _fake_client([_FakeNumber("+15551230002", None)], _FakeNumber("+15551230002", "PNyyyy"))
    svc = client.messaging.v1.services.return_value
    svc.phone_numbers.create.side_effect = RuntimeError("already associated")
    existing = MagicMock()
    existing.sid = "PNyyyy"
    svc.phone_numbers.list.return_value = [existing]
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda sid, tok: client)

    out = twilio_provision.purchase_number(account_sid="AC", auth_token="tok", base_url=BASE)
    assert out["messaging_service_enrolled"] is True
    assert out["errors"] == []


def test_purchase_enroll_failure_is_non_fatal(monkeypatch):
    monkeypatch.setenv("TWILIO_A2P_MESSAGING_SERVICE_SID", "MG123")
    client = _fake_client([_FakeNumber("+15551230003", None)], _FakeNumber("+15551230003", "PNzzzz"))
    svc = client.messaging.v1.services.return_value
    svc.phone_numbers.create.side_effect = RuntimeError("boom")
    svc.phone_numbers.list.return_value = []  # confirms it's not in the service
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda sid, tok: client)

    out = twilio_provision.purchase_number(account_sid="AC", auth_token="tok", base_url=BASE)
    assert out["ok"] is True  # the number was still bought + configured
    assert out["messaging_service_enrolled"] is False
    assert "messaging_service_enroll_failed" in out["errors"]


def test_purchase_skips_enrollment_when_unconfigured(monkeypatch):
    monkeypatch.delenv("TWILIO_A2P_MESSAGING_SERVICE_SID", raising=False)
    client = _fake_client([_FakeNumber("+15551230004", None)], _FakeNumber("+15551230004", "PNwww"))
    monkeypatch.setattr(twilio_provision, "TwilioClient", lambda sid, tok: client)

    out = twilio_provision.purchase_number(account_sid="AC", auth_token="tok", base_url=BASE)
    assert out["ok"] is True
    assert out["messaging_service_enrolled"] is False
    client.messaging.v1.services.return_value.phone_numbers.create.assert_not_called()
