"""Tests for Twilio recording-complete webhook and authenticated recording playback."""
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)
    return TestClient(app)


def _tenant_pro():
    return {"plan": "pro", "client_id": "test-spa", "id": "123", "subscription_status": "active"}


def test_recording_complete_persists_and_returns_200(client, monkeypatch):
    monkeypatch.setattr("main._validate_twilio_webhook", lambda req, d: True)
    monkeypatch.setenv("CALL_SUMMARY_ENABLED", "false")
    monkeypatch.setattr("main.USE_DB", True)
    monkeypatch.setattr("main.active_calls", {})

    updates = []

    def fake_upsert(call_sid, client_id, **kw):
        updates.append({"call_sid": call_sid, "client_id": client_id, **kw})
        return True

    monkeypatch.setattr("main.db_call_log_update_recording", fake_upsert)
    monkeypatch.setattr("main.db_call_log_get_client_id_by_call_sid", lambda sid: "test-spa")

    resp = client.post(
        "/api/phone/recording-complete",
        data={
            "CallSid": "CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "RecordingSid": "REyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
            "RecordingUrl": "https://api.twilio.com/2010-04-01/Accounts/AC/Recordings/RE",
            "RecordingDuration": "42",
            "RecordingStatus": "completed",
        },
    )
    assert resp.status_code == 200
    assert len(updates) == 1
    assert updates[0]["call_sid"] == "CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    assert updates[0]["client_id"] == "test-spa"
    assert updates[0]["recording_sid"] == "REyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
    assert updates[0]["recording_duration_sec"] == 42
    assert updates[0]["recording_status"] == "completed"


def test_recording_complete_invalid_signature_403(client, monkeypatch):
    monkeypatch.setattr("main._validate_twilio_webhook", lambda req, d: False)
    resp = client.post(
        "/api/phone/recording-complete",
        data={"CallSid": "CAx", "RecordingStatus": "completed"},
    )
    assert resp.status_code == 403


def test_recording_playback_404_when_no_row(client, monkeypatch):
    from main import require_tenant

    app.dependency_overrides[require_tenant] = _tenant_pro
    monkeypatch.setattr("main.USE_DB", True)
    monkeypatch.setattr("main.TWILIO_ACCOUNT_SID", "ACxxx")
    monkeypatch.setattr("main.TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setattr("main.db_call_log_get_by_call_sid", lambda cid, sid: None)
    try:
        resp = client.get("/api/analytics/calls/CAnotfound/recording")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(require_tenant, None)


def test_recording_playback_404_when_no_recording_url(client, monkeypatch):
    from main import require_tenant

    app.dependency_overrides[require_tenant] = _tenant_pro
    monkeypatch.setattr("main.USE_DB", True)
    monkeypatch.setattr("main.TWILIO_ACCOUNT_SID", "ACxxx")
    monkeypatch.setattr("main.TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setattr(
        "main.db_call_log_get_by_call_sid",
        lambda cid, sid: {"call_sid": sid, "recording_url": None, "client_id": cid},
    )
    try:
        resp = client.get("/api/analytics/calls/CA123/recording")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(require_tenant, None)
