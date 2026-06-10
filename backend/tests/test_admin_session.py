"""Regression test for GET /api/admin/session.

This endpoint had zero coverage and shipped a NameError to production: it called
`verify_clerk_token(token)` bare (the symbol lives in auth.py and is re-exported by
deps), so every call 500'd and no one could enter the dashboard. The fix qualifies it
as `deps.verify_clerk_token`. These tests exercise the real handler through the route,
so a bare/undefined call would surface as a 500 here instead of in prod.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import deps
import main

client = TestClient(main.app)


def test_admin_session_true_for_allowlisted_user(monkeypatch):
    monkeypatch.setenv("ADMIN_CLERK_USER_IDS", "user_admin,user_other")
    monkeypatch.setattr(deps, "verify_clerk_token", lambda t: ("user_admin", None))
    r = client.get("/api/admin/session", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json() == {"is_admin": True}


def test_admin_session_false_for_non_admin_user(monkeypatch):
    monkeypatch.setenv("ADMIN_CLERK_USER_IDS", "user_admin")
    monkeypatch.setattr(deps, "verify_clerk_token", lambda t: ("user_random", None))
    r = client.get("/api/admin/session", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json() == {"is_admin": False}


def test_admin_session_false_without_token():
    r = client.get("/api/admin/session")
    assert r.status_code == 200
    assert r.json() == {"is_admin": False}
