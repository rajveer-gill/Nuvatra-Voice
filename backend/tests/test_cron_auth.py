"""Tests for cron endpoint auth (X-Cron-Secret)."""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_cron_appointment_reminders_401_without_secret(client, monkeypatch):
    """POST /api/cron/appointment-reminders without X-Cron-Secret returns 401."""
    monkeypatch.setenv("CRON_SECRET", "test-secret-xyz")
    resp = client.post("/api/cron/appointment-reminders")
    assert resp.status_code == 401


def test_cron_appointment_reminders_200_with_valid_secret(client, monkeypatch):
    """POST /api/cron/appointment-reminders with valid X-Cron-Secret returns 200."""
    secret = "test-cron-secret-123"
    monkeypatch.setenv("CRON_SECRET", secret)
    resp = client.post(
        "/api/cron/appointment-reminders",
        headers={"X-Cron-Secret": secret},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "reminders_sent" in data
    assert "errors" in data
    assert "tenants_processed" in data


def test_cron_appointment_reminders_401_with_wrong_secret(client, monkeypatch):
    """POST /api/cron/appointment-reminders with wrong secret returns 401."""
    monkeypatch.setenv("CRON_SECRET", "correct-secret")
    resp = client.post(
        "/api/cron/appointment-reminders",
        headers={"X-Cron-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401


def test_cron_process_overage_401_without_secret(client):
    """POST /api/cron/process-overage without X-Cron-Secret returns 401."""
    resp = client.post("/api/cron/process-overage")
    assert resp.status_code == 401


def test_cron_process_overage_200_with_valid_secret(client, monkeypatch):
    """POST /api/cron/process-overage with valid X-Cron-Secret returns 200."""
    secret = "test-overage-secret-456"
    monkeypatch.setenv("CRON_SECRET", secret)
    resp = client.post(
        "/api/cron/process-overage",
        headers={"X-Cron-Secret": secret},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "tenants_processed" in data
    assert "invoices_created" in data
    assert "errors" in data


def test_cron_retention_purge_401_without_secret(client):
    resp = client.post("/api/cron/retention-purge")
    assert resp.status_code == 401


def test_cron_retention_purge_200_with_valid_secret(client, monkeypatch):
    secret = "test-retention-secret-789"
    monkeypatch.setenv("CRON_SECRET", secret)
    resp = client.post(
        "/api/cron/retention-purge",
        headers={"X-Cron-Secret": secret},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "deleted" in data


def test_cron_export_snapshot_401_without_secret(client):
    resp = client.post("/api/cron/export-snapshot")
    assert resp.status_code == 401


def test_cron_export_snapshot_200_with_valid_secret(client, monkeypatch):
    secret = "test-export-secret-321"
    monkeypatch.setenv("CRON_SECRET", secret)
    resp = client.post(
        "/api/cron/export-snapshot",
        headers={"X-Cron-Secret": secret},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "exported" in data
