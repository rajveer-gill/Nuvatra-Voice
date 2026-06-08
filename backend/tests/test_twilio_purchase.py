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
