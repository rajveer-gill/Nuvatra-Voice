"""Admin audit-log read path: db query + endpoint (admin-gated)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app, require_admin


def test_db_audit_list_filters_and_caps_limit():
    with patch.object(database, "_get_conn") as mc:
        cur = mc.return_value.cursor.return_value
        cur.fetchall.return_value = []
        database.db_audit_list(limit=9999, client_id="acme", action="auth_failure")
        sql, params = cur.execute.call_args[0]
    assert "WHERE client_id = %s AND action = %s" in sql
    assert "ORDER BY occurred_at DESC LIMIT %s" in sql
    assert params[0] == "acme" and params[1] == "auth_failure"
    assert params[2] == 500  # capped


def test_db_audit_list_maps_rows():
    now = datetime(2026, 6, 8, tzinfo=timezone.utc)
    with patch.object(database, "_get_conn") as mc:
        cur = mc.return_value.cursor.return_value
        cur.fetchall.return_value = [
            (1, now, "admin", "u_1", "tenant_create", "tenant", "t1", "acme", "1.2.3.4"),
        ]
        out = database.db_audit_list()
    assert out[0]["action"] == "tenant_create"
    assert out[0]["actor_id"] == "u_1"
    assert out[0]["client_id"] == "acme"
    assert out[0]["ip"] == "1.2.3.4"
    assert "details" not in out[0]  # blob intentionally excluded


def test_audit_endpoint_requires_admin():
    # No override -> require_admin rejects (401/403), never 200.
    resp = TestClient(app).get("/api/admin/audit")
    assert resp.status_code in (401, 403)


def test_audit_endpoint_returns_events_for_admin(monkeypatch):
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    monkeypatch.setattr(
        "database.db_audit_list",
        lambda **kw: [{"id": 1, "action": "tenant_create", "actor_id": "u_1"}],
    )
    try:
        resp = TestClient(app).get("/api/admin/audit?limit=50")
        assert resp.status_code == 200
        assert resp.json()["events"][0]["action"] == "tenant_create"
    finally:
        app.dependency_overrides.clear()
