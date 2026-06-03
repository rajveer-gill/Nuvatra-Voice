"""Twilio webhook auto-config tests."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from twilio_provision import (
    configure_webhooks,
    normalize_e164,
    reset_webhook_verify_cache_for_tests,
    validate_public_base_url,
    verify_webhooks_match,
    verify_webhooks_match_cached,
)


def test_normalize_e164_us():
    assert normalize_e164("5551234567") == "+15551234567"
    assert normalize_e164("+15551234567") == "+15551234567"


def test_validate_public_base_url_rejects_insecure():
    origin, errors = validate_public_base_url("http://api.example.com")
    assert not origin
    assert "public_base_url_must_be_https" in errors

    origin, errors = validate_public_base_url("https://api.example.com/extra/path")
    assert not origin
    assert "public_base_url_must_be_origin_only" in errors

    origin, errors = validate_public_base_url("https://user:pass@api.example.com")
    assert not origin
    assert "public_base_url_must_not_include_credentials" in errors

    origin, errors = validate_public_base_url("https://api.example.com")
    assert origin == "https://api.example.com"
    assert not errors


@patch("twilio_provision.verify_webhooks_match")
def test_verify_webhooks_match_cached(mock_verify):
    reset_webhook_verify_cache_for_tests()
    mock_verify.return_value = {"webhooks_configured": True, "voice_ok": True, "sms_ok": True, "status_ok": True, "errors": []}
    kwargs = dict(
        account_sid="AC",
        auth_token="tok",
        phone="+15551234567",
        base_url="https://api.example.com",
    )
    first = verify_webhooks_match_cached(**kwargs)
    second = verify_webhooks_match_cached(**kwargs)
    assert first["webhooks_configured"] is True
    assert second["webhooks_configured"] is True
    assert mock_verify.call_count == 1


@patch("twilio_provision.TwilioClient")
def test_configure_webhooks_success(mock_client_cls):
    number = MagicMock()
    number.sid = "PN123"
    client = MagicMock()
    client.incoming_phone_numbers.list.return_value = [number]
    mock_client_cls.return_value = client

    result = configure_webhooks(
        account_sid="ACtest",
        auth_token="token",
        phone="+15551234567",
        base_url="https://api.example.com",
    )
    assert result["voice_ok"] is True
    assert result["sms_ok"] is True
    number.update.assert_called_once()


@patch("twilio_provision.TwilioClient")
def test_configure_webhooks_number_missing(mock_client_cls):
    client = MagicMock()
    client.incoming_phone_numbers.list.return_value = []
    mock_client_cls.return_value = client
    result = configure_webhooks(
        account_sid="ACtest",
        auth_token="token",
        phone="+15559998888",
        base_url="https://api.example.com",
    )
    assert result["voice_ok"] is False
    assert result["errors"]


@patch("twilio_provision.find_incoming_number")
@patch("twilio_provision.TwilioClient")
def test_verify_webhooks_match(mock_client_cls, mock_find):
    number = MagicMock()
    number.voice_url = "https://api.example.com/api/phone/incoming"
    number.sms_url = "https://api.example.com/api/sms/incoming"
    number.status_callback = "https://api.example.com/api/phone/status"
    mock_find.return_value = number
    mock_client_cls.return_value = MagicMock()

    out = verify_webhooks_match(
        account_sid="AC",
        auth_token="tok",
        phone="+15551234567",
        base_url="https://api.example.com",
    )
    assert out["webhooks_configured"] is True


def test_twilio_phone_patch_requires_auth():
    client = TestClient(app)
    resp = client.patch(
        "/api/admin/tenants/00000000-0000-0000-0000-000000000001/twilio-phone",
        json={"twilio_phone_number": "+15550001111"},
    )
    assert resp.status_code in (401, 403, 404, 503)
