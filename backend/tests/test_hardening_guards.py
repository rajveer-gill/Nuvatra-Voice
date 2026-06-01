import pytest
from fastapi.testclient import TestClient

import main
from auth import verify_clerk_token


def test_verify_clerk_token_requires_issuer_and_audience(monkeypatch):
    monkeypatch.setenv("CLERK_JWKS_URL", "https://example.test/.well-known/jwks.json")
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.delenv("CLERK_AUDIENCE", raising=False)
    with pytest.raises(Exception) as exc:
        verify_clerk_token("fake.jwt")
    assert getattr(exc.value, "status_code", None) == 500


def test_twilio_webhook_validation_fail_closed_in_db(monkeypatch):
    monkeypatch.setattr(main, "USE_DB", True)
    monkeypatch.setattr(main, "TWILIO_AVAILABLE", True)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_WEBHOOKS", raising=False)

    class DummyReq:
        headers = {}
        url = "https://example.test/twilio"

    assert main._validate_twilio_webhook(DummyReq(), {}) is False


def test_call_runtime_cleanup_clears_response_status():
    call_sid = "CA_cleanup_test"
    main.active_calls[call_sid] = {"client_id": "tenant-a"}
    main.response_status[call_sid] = {"status": "pending"}
    main.cleanup_call_runtime_state(call_sid)
    assert call_sid not in main.active_calls
    assert call_sid not in main.response_status


def test_phone_status_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(main, "_validate_twilio_webhook", lambda req, data: False)
    client = TestClient(main.app)
    resp = client.post("/api/phone/status", data={"CallSid": "CAx", "CallStatus": "completed"})
    assert resp.status_code == 403

