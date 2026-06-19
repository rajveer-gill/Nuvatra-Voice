"""Tests for bring-your-own-number: mode switch + forwarding verification."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import config_service
from routers import business as biz


# ---- forwarding verification (ForwardedFrom match) ----

def test_forwarding_verify_on_match(monkeypatch):
    cfg = {"number_mode": "existing", "existing_business_number": "+14155550123", "forwarding_verified_at": ""}
    saved = {}
    monkeypatch.setattr(config_service, "load_client_config", lambda cid: dict(cfg))
    monkeypatch.setattr(config_service, "save_raw_client_config", lambda cid, data: saved.update(data))
    # Twilio sends ForwardedFrom = the number that forwarded the call.
    assert config_service.mark_forwarding_verified_if_match("c1", "+1 (415) 555-0123") is True
    assert saved.get("forwarding_verified_at")


def test_forwarding_verify_mismatch(monkeypatch):
    cfg = {"number_mode": "existing", "existing_business_number": "+14155550123", "forwarding_verified_at": ""}
    monkeypatch.setattr(config_service, "load_client_config", lambda cid: dict(cfg))
    monkeypatch.setattr(config_service, "save_raw_client_config", lambda cid, data: None)
    assert config_service.mark_forwarding_verified_if_match("c1", "+19998887777") is False


def test_forwarding_verify_ignored_when_not_existing_mode(monkeypatch):
    monkeypatch.setattr(config_service, "load_client_config", lambda cid: {"number_mode": "new"})
    assert config_service.mark_forwarding_verified_if_match("c1", "+14155550123") is False


def test_forwarding_verify_idempotent(monkeypatch):
    cfg = {
        "number_mode": "existing", "existing_business_number": "+14155550123",
        "forwarding_verified_at": "2026-01-01T00:00:00Z",
    }
    monkeypatch.setattr(config_service, "load_client_config", lambda cid: dict(cfg))
    assert config_service.mark_forwarding_verified_if_match("c1", "+14155550123") is False


# ---- mode switch endpoint ----

def test_switch_to_existing_persists_and_resets_verification(monkeypatch):
    saved = {}
    monkeypatch.setattr(biz.config_service, "_read_raw_client_config", lambda cid: {"number_mode": "new", "forwarding_verified_at": "old"})
    monkeypatch.setattr(biz.config_service, "save_raw_client_config", lambda cid, data: saved.update(data))
    monkeypatch.setattr(biz.deps, "audit_log", lambda *a, **k: None)
    res = biz.api_update_number_mode(
        biz.UpdateNumberModeRequest(number_mode="existing", existing_number="(415) 555-0123"),
        request=MagicMock(),
        tenant={"client_id": "c1", "id": "t1"},
    )
    assert res["number_mode"] == "existing"
    assert saved["number_mode"] == "existing"
    assert saved["existing_business_number"]
    assert saved["forwarding_verified_at"] == ""  # changed -> re-verify


def test_switch_to_new(monkeypatch):
    saved = {}
    monkeypatch.setattr(biz.config_service, "_read_raw_client_config", lambda cid: {"number_mode": "existing"})
    monkeypatch.setattr(biz.config_service, "save_raw_client_config", lambda cid, data: saved.update(data))
    monkeypatch.setattr(biz.deps, "audit_log", lambda *a, **k: None)
    res = biz.api_update_number_mode(
        biz.UpdateNumberModeRequest(number_mode="new"),
        request=MagicMock(),
        tenant={"client_id": "c1", "id": "t1"},
    )
    assert res["number_mode"] == "new"
    assert saved["number_mode"] == "new"


def test_existing_requires_valid_number(monkeypatch):
    monkeypatch.setattr(biz.config_service, "_read_raw_client_config", lambda cid: {})
    with pytest.raises(HTTPException) as exc:
        biz.api_update_number_mode(
            biz.UpdateNumberModeRequest(number_mode="existing", existing_number="123"),
            request=MagicMock(),
            tenant={"client_id": "c1"},
        )
    assert exc.value.status_code == 400
