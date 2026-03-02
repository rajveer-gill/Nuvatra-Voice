"""Integration tests for SMS webhook."""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


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
