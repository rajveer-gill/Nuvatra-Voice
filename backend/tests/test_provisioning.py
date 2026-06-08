"""Idempotent per-tenant provisioning step machine."""

from __future__ import annotations

import provisioning


CREDS = dict(base_url="https://api.example.com", account_sid="AC", auth_token="tok")


def _patch_all(monkeypatch, *, existing_number=None, purchase_ok=True):
    """Stub every collaborator; return a calls-log dict."""
    calls = {"created": 0, "purchased": 0, "phone_set": 0, "config": 0, "clerk": 0}

    def db_tenant_create(**kw):
        calls["created"] += 1
        return {"id": "tid-1", "client_id": kw["client_id"]}

    def db_tenant_get_by_client_id(cid):
        return {"id": "tid-1", "client_id": cid, "twilio_phone_number": existing_number or ""}

    def db_tenant_set_twilio_phone(tid, phone):
        calls["phone_set"] += 1
        return True

    def purchase_number(**kw):
        calls["purchased"] += 1
        return {"ok": purchase_ok, "phone_e164": "+14155550001", "number_sid": "PN", "errors": [] if purchase_ok else ["no_available_numbers"]}

    def default_cfg(cid, plan):
        return {"client_id": cid, "plan": plan}

    def save_cfg(cid, cfg):
        calls["config"] += 1

    def clerk_link(email, tid):
        calls["clerk"] += 1
        return {"invite_sent": True}

    monkeypatch.setattr("database.db_tenant_create", db_tenant_create)
    monkeypatch.setattr("database.db_tenant_get_by_client_id", db_tenant_get_by_client_id)
    monkeypatch.setattr("database.db_tenant_set_twilio_phone", db_tenant_set_twilio_phone)
    monkeypatch.setattr("twilio_provision.purchase_number", purchase_number)
    monkeypatch.setattr("config_service._default_client_config_data", default_cfg)
    monkeypatch.setattr("config_service.save_raw_client_config", save_cfg)
    monkeypatch.setattr("clerk_service._clerk_link_email_to_tenant", clerk_link)
    return calls


def test_happy_path_runs_all_steps(monkeypatch):
    calls = _patch_all(monkeypatch)
    task = {"client_id": "acme", "name": "Acme", "email": "o@acme.com", "steps_done": []}
    out = provisioning.provision_one_tenant(task, **CREDS)
    assert out["status"] == "done"
    assert out["steps_done"] == ["clerk_invited", "config_seeded", "number_purchased", "tenant_created"]
    assert out["phone_e164"] == "+14155550001"
    assert calls == {"created": 1, "purchased": 1, "phone_set": 1, "config": 1, "clerk": 1}


def test_skips_purchase_when_phone_already_provided(monkeypatch):
    calls = _patch_all(monkeypatch)
    task = {"client_id": "acme", "name": "Acme", "email": "o@acme.com", "phone_e164": "+14155559999", "steps_done": []}
    out = provisioning.provision_one_tenant(task, **CREDS)
    assert out["status"] == "done"
    assert out["phone_e164"] == "+14155559999"
    assert calls["purchased"] == 0  # never bought
    assert calls["phone_set"] == 0


def test_skips_purchase_when_tenant_already_has_number(monkeypatch):
    calls = _patch_all(monkeypatch, existing_number="+14155551111")
    task = {"client_id": "acme", "email": "o@acme.com", "steps_done": []}
    out = provisioning.provision_one_tenant(task, **CREDS)
    assert out["status"] == "done"
    assert calls["purchased"] == 0


def test_resume_skips_completed_steps(monkeypatch):
    calls = _patch_all(monkeypatch)
    task = {
        "client_id": "acme", "name": "Acme", "email": "o@acme.com",
        "phone_e164": "+14155550001",
        "steps_done": ["tenant_created", "number_purchased", "config_seeded"],
    }
    out = provisioning.provision_one_tenant(task, **CREDS)
    assert out["status"] == "done"
    # only clerk remained
    assert calls == {"created": 0, "purchased": 0, "phone_set": 0, "config": 0, "clerk": 1}


def test_purchase_failure_marks_failed_and_preserves_progress(monkeypatch):
    calls = _patch_all(monkeypatch, purchase_ok=False)
    task = {"client_id": "acme", "email": "o@acme.com", "steps_done": []}
    out = provisioning.provision_one_tenant(task, **CREDS)
    assert out["status"] == "failed"
    assert "twilio_purchase_failed" in out["error"]
    assert "tenant_created" in out["steps_done"]      # progress kept for resume
    assert "number_purchased" not in out["steps_done"]
    assert calls["config"] == 0 and calls["clerk"] == 0  # stopped at failed step


def test_no_email_skips_clerk(monkeypatch):
    calls = _patch_all(monkeypatch)
    task = {"client_id": "acme", "steps_done": []}
    out = provisioning.provision_one_tenant(task, **CREDS)
    assert out["status"] == "done"
    assert "clerk_invited" not in out["steps_done"]
    assert calls["clerk"] == 0
