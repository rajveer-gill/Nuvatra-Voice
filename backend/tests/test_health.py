"""Health endpoint behavior."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


def test_health_ok_without_db():
    client = TestClient(app)
    with patch("main.USE_DB", False):
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["database"] == "n/a"


def test_health_ok_with_db():
    client = TestClient(app)
    with patch("main.USE_DB", True), patch("main.db_ping", return_value=True):
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["database"] == "ok"


def test_health_503_when_db_unreachable():
    client = TestClient(app)
    with patch("main.USE_DB", True), patch("main.db_ping", return_value=False):
        resp = client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert resp.json()["database"] == "error"
