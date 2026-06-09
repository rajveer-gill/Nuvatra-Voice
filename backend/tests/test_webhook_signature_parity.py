"""Characterization safety net for the Twilio webhook endpoints (SMS + phone-incoming).

These are the highest-risk routes still in main.py and the next extraction targets.
This suite locks their externally-observable security contract by driving the HTTP
endpoint with REAL Twilio signatures — it patches no internal symbols, so it will keep
passing byte-for-byte after the handlers move into routers/ (proving the extraction was
behavior-preserving). Pair with the existing TwiML-shape tests (test_phone_incoming_twiml,
test_sms) which characterize the handler output itself.

Strict signature enforcement is `USE_DB and not ALLOW_INSECURE_WEBHOOKS` (see
deps._validate_twilio_webhook); the 403 short-circuits before any DB work, so the
rejection cases need no real database.
"""

import os

import pytest
from fastapi.testclient import TestClient

from main import app, TWILIO_AVAILABLE

pytestmark = pytest.mark.skipif(
    not TWILIO_AVAILABLE, reason="twilio package required for signature validation"
)

from twilio.request_validator import RequestValidator  # noqa: E402

TOKEN = "AC_characterization_test_token_0123456789"
SMS_FORM = {
    "From": "+15551230000",
    "To": "+15557890000",
    "Body": "hello there",
    "MessageSid": "SM00000000000000000000000000000001",
}
CALL_FORM = {
    "From": "+15551230000",
    "To": "+15557890000",
    "CallSid": "CA00000000000000000000000000000001",
}


@pytest.fixture
def strict_client(monkeypatch):
    """USE_DB=True + auth token + no insecure override => strict signature enforcement."""
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.delenv("ALLOW_INSECURE_WEBHOOKS", raising=False)
    return TestClient(app)


def _valid_signature(path: str, params: dict) -> str:
    # Mirrors security.webhooks.validate_twilio_webhook: signs str(request.url) + params.
    url = f"http://testserver{path}"
    return RequestValidator(TOKEN).compute_signature(url, params)


# --- rejection cases (deterministic, no DB needed: 403 short-circuits) ---------

@pytest.mark.parametrize(
    "path,form",
    [("/api/sms/incoming", SMS_FORM), ("/api/phone/incoming", CALL_FORM)],
)
def test_missing_signature_rejected_in_strict_mode(strict_client, path, form):
    resp = strict_client.post(path, data=form)
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "path,form",
    [("/api/sms/incoming", SMS_FORM), ("/api/phone/incoming", CALL_FORM)],
)
def test_bad_signature_rejected_in_strict_mode(strict_client, path, form):
    resp = strict_client.post(
        path, data=form, headers={"X-Twilio-Signature": "obviously-not-valid"}
    )
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "path,form",
    [("/api/sms/incoming", SMS_FORM), ("/api/phone/incoming", CALL_FORM)],
)
def test_valid_signature_passes_the_gate(strict_client, path, form):
    """A correctly-signed request must NOT be rejected as a bad signature (403)."""
    sig = _valid_signature(path, form)
    resp = strict_client.post(path, data=form, headers={"X-Twilio-Signature": sig})
    assert resp.status_code != 403


# --- early-exit contract (SMS returns empty TwiML when DB is off) --------------

def test_sms_returns_empty_twiml_when_db_disabled(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", False)
    resp = TestClient(app).post("/api/sms/incoming", data=SMS_FORM)
    assert resp.status_code == 200
    assert "xml" in resp.headers.get("content-type", "").lower()
    assert "<Response>" in resp.text and "</Response>" in resp.text
