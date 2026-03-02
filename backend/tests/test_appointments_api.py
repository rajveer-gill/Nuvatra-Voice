"""Integration tests for appointments API."""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_appointments(client):
    """GET /api/appointments returns 200 or 403 depending on auth/config."""
    resp = client.get("/api/appointments")
    assert resp.status_code in (200, 401, 403)


def test_root(client):
    """GET / returns API info."""
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data or "status" in data


def test_debug_cors(client):
    """GET /api/debug/cors returns allowed origins."""
    resp = client.get("/api/debug/cors")
    assert resp.status_code == 200
