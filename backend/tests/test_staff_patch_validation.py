"""Validation for staff fields on PATCH /api/business-info."""
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app, require_tenant


def _tenant_pro():
    return {
        "id": "test-tenant-id",
        "client_id": "test-spa",
        "plan": "pro",
        "subscription_status": "active",
        "twilio_phone_number": "+15550001111",
    }


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)
    # Isolate on-disk config writes (PATCH /api/business-info) to a tmp dir so the
    # real clients/<CLIENT_ID>/config.json is never touched. See test_business_config_storage.py.
    monkeypatch.setattr("config_service.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("main.PROJECT_ROOT", tmp_path)
    return TestClient(app)


def test_staff_empty_phone_allowed(client, monkeypatch):
    app.dependency_overrides[require_tenant] = _tenant_pro
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    try:
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Tom",
                        "phone": "",
                        "email": "",
                        "notes": "",
                    }
                ],
            },
        )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(require_tenant, None)


def test_staff_short_phone_returns_422(client, monkeypatch):
    app.dependency_overrides[require_tenant] = _tenant_pro
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    try:
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Tom",
                        "phone": "555",
                        "email": "",
                        "notes": "",
                    }
                ],
            },
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(require_tenant, None)


def test_staff_invalid_email_returns_422(client, monkeypatch):
    app.dependency_overrides[require_tenant] = _tenant_pro
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    try:
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Test",
                        "phone": "+15551234567",
                        "email": "not-valid-email",
                        "notes": "",
                    }
                ],
            },
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(require_tenant, None)


def test_staff_notes_over_max_returns_422(client, monkeypatch):
    app.dependency_overrides[require_tenant] = _tenant_pro
    monkeypatch.setenv("CLIENT_ID", "test-spa")
    try:
        resp = client.patch(
            "/api/business-info",
            json={
                "staff": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Test",
                        "phone": "+15551234567",
                        "email": "",
                        "notes": "x" * 4100,
                    }
                ],
            },
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(require_tenant, None)
