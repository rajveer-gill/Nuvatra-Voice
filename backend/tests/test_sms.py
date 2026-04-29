"""Integration tests for SMS webhook."""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_sms_compliance_stop_sets_opt_out_and_force_sends(client, monkeypatch):
    monkeypatch.setattr("main.USE_DB", True)
    monkeypatch.setattr("main._validate_twilio_webhook", lambda r, d: True)
    monkeypatch.setattr(
        "main.db_tenant_get_by_phone",
        lambda num: {"client_id": "test-spa", "name": "Test Biz"},
    )
    opted = []
    monkeypatch.setattr(
        "main.db_sms_opt_out_set",
        lambda phone, cid: opted.append((phone, cid)),
    )
    sends = []

    def capture_send(to, body, from_override=None, *, force=False):
        sends.append({"to": to, "force": force, "snippet": (body or "")[:40]})
        return True

    monkeypatch.setattr("main.send_sms", capture_send)
    resp = client.post(
        "/api/sms/incoming",
        data={"From": "+15551110000", "To": "+15552220000", "Body": "STOP"},
    )
    assert resp.status_code == 200
    assert len(opted) == 1
    assert sends and sends[0].get("force") is True


def test_sms_compliance_start_clears_opt_out(client, monkeypatch):
    monkeypatch.setattr("main.USE_DB", True)
    monkeypatch.setattr("main._validate_twilio_webhook", lambda r, d: True)
    monkeypatch.setattr(
        "main.db_tenant_get_by_phone",
        lambda num: {"client_id": "test-spa", "name": "Test Biz"},
    )
    cleared = []
    monkeypatch.setattr(
        "main.db_sms_opt_out_clear",
        lambda phone, cid: cleared.append((phone, cid)),
    )
    sends = []

    def capture_send(to, body, from_override=None, *, force=False):
        sends.append({"force": force})
        return True

    monkeypatch.setattr("main.send_sms", capture_send)
    resp = client.post(
        "/api/sms/incoming",
        data={"From": "+15551110000", "To": "+15552220000", "Body": "START"},
    )
    assert resp.status_code == 200
    assert len(cleared) == 1
    assert sends and sends[0].get("force") is True


def test_sms_inbound_ignored_when_opted_out(client, monkeypatch):
    monkeypatch.setattr("main.USE_DB", True)
    monkeypatch.setattr("main._validate_twilio_webhook", lambda r, d: True)
    monkeypatch.setattr(
        "main.db_tenant_get_by_phone",
        lambda num: {"client_id": "test-spa", "name": "Test Biz"},
    )
    monkeypatch.setattr("main.db_sms_opt_out_is_blocked", lambda phone, cid: True)
    send_calls = []
    monkeypatch.setattr("main.send_sms", lambda *a, **k: send_calls.append(1) or True)
    resp = client.post(
        "/api/sms/incoming",
        data={"From": "+15551110000", "To": "+15552220000", "Body": "Hello there"},
    )
    assert resp.status_code == 200
    assert send_calls == []


def test_sms_incoming_returns_xml(client):
    """POST /api/sms/incoming returns 200 and valid TwiML."""
    resp = client.post(
        "/api/sms/incoming",
        data={"From": "+15551234567", "To": "+15559876543", "Body": "Hello"},
    )
    assert resp.status_code == 200
    assert "xml" in resp.headers.get("content-type", "").lower()
    assert "<Response>" in resp.text


def test_sms_incoming_missing_params(client):
    """POST with missing From/To/Body still returns 200 (graceful)."""
    resp = client.post("/api/sms/incoming", data={})
    assert resp.status_code == 200
