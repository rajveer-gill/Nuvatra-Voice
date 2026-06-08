"""Background provisioning worker + admin endpoints."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import provisioning
from main import app, require_admin


# --- worker ---------------------------------------------------------------

def test_run_job_processes_tasks_and_sets_status(monkeypatch):
    saved = []
    statuses = []
    monkeypatch.setattr(
        "database.db_provisioning_job_set_status",
        lambda jid, s: statuses.append(s),
    )
    monkeypatch.setattr(
        "database.db_provisioning_tasks_for_job",
        lambda jid, only_unfinished=False: [
            {"id": 1, "client_id": "a", "steps_done": []},
            {"id": 2, "client_id": "b", "steps_done": []},
        ],
    )
    monkeypatch.setattr(
        "database.db_provisioning_task_save",
        lambda tid, **kw: saved.append((tid, kw["status"])),
    )
    monkeypatch.setattr("database.db_release_thread_connection", lambda: None)

    def fake_provision(task, **kw):
        return {**task, "status": "done" if task["client_id"] == "a" else "failed",
                "steps_done": ["tenant_created"], "phone_e164": None, "error": None}

    monkeypatch.setattr(provisioning, "provision_one_tenant", fake_provision)

    summary = asyncio.run(
        provisioning.run_provisioning_job(
            "job-1", base_url="https://x", account_sid="AC", auth_token="t", concurrency=2
        )
    )
    assert summary == {"done": 1, "failed": 1, "total": 2}
    assert statuses == ["running", "failed"]  # any failure -> job failed
    assert sorted(saved) == [(1, "done"), (2, "failed")]


# --- endpoints ------------------------------------------------------------

@pytest.fixture
def admin_client(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_create_job_persists_and_kicks_worker(admin_client, monkeypatch):
    created = {}
    monkeypatch.setattr("database.db_provisioning_job_create", lambda jid, by, total: created.update(id=jid, total=total) or True)
    monkeypatch.setattr("database.db_provisioning_task_create", lambda *a, **k: 1)
    # don't actually run the worker
    async def noop(*a, **k):
        return {"done": 0, "failed": 0, "total": 0}
    monkeypatch.setattr(provisioning, "run_provisioning_job", noop)

    resp = admin_client.post(
        "/api/admin/provisioning/jobs",
        json={"tenants": [
            {"client_id": "acme", "name": "Acme", "email": "o@acme.com"},
            {"client_id": "beta", "name": "Beta"},
        ]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2 and body["status"] == "running" and body["job_id"]
    assert created["total"] == 2


def test_create_job_rejects_duplicate_client_ids(admin_client):
    resp = admin_client.post(
        "/api/admin/provisioning/jobs",
        json={"tenants": [{"client_id": "dup"}, {"client_id": "dup"}]},
    )
    assert resp.status_code == 400
    assert "duplicate" in resp.json()["detail"]


def test_create_job_503_when_unconfigured(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        client = TestClient(app)
        resp = client.post("/api/admin/provisioning/jobs", json={"tenants": [{"client_id": "acme"}]})
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_get_job_404_when_missing(admin_client, monkeypatch):
    monkeypatch.setattr("database.db_provisioning_job_get", lambda jid: None)
    resp = admin_client.get("/api/admin/provisioning/jobs/nope")
    assert resp.status_code == 404


def test_get_job_returns_tasks(admin_client, monkeypatch):
    monkeypatch.setattr("database.db_provisioning_job_get", lambda jid: {"id": jid, "status": "done", "counts": {"done": 1}})
    monkeypatch.setattr("database.db_provisioning_tasks_for_job", lambda jid, only_unfinished=False: [{"id": 1, "client_id": "acme", "status": "done"}])
    resp = admin_client.get("/api/admin/provisioning/jobs/job-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["tasks"][0]["client_id"] == "acme"
