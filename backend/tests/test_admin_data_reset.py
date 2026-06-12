"""TEMPORARY pre-launch data-reset endpoint — triple-gated (admin + env flag + confirm)."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import database
import deps
from routers import admin


def test_reset_disabled_without_env_flag(monkeypatch):
    monkeypatch.delenv("ALLOW_DATA_RESET", raising=False)
    with pytest.raises(HTTPException) as exc:
        admin.admin_reset_all_data(
            admin.AdminResetDataRequest(confirm="RESET"), request=MagicMock(), admin_user_id="a1"
        )
    assert exc.value.status_code == 403


def test_reset_requires_typed_confirmation(monkeypatch):
    monkeypatch.setenv("ALLOW_DATA_RESET", "1")
    with pytest.raises(HTTPException) as exc:
        admin.admin_reset_all_data(
            admin.AdminResetDataRequest(confirm="nope"), request=MagicMock(), admin_user_id="a1"
        )
    assert exc.value.status_code == 400


def test_reset_runs_when_enabled_and_confirmed(monkeypatch):
    monkeypatch.setenv("ALLOW_DATA_RESET", "1")
    monkeypatch.setattr("runtime.USE_DB", True)
    called = {"n": 0}
    monkeypatch.setattr(database, "db_reset_all_tenant_data", lambda: called.update(n=called["n"] + 1) or True)
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    out = admin.admin_reset_all_data(
        admin.AdminResetDataRequest(confirm="RESET"), request=MagicMock(), admin_user_id="a1"
    )
    assert out["success"] is True
    assert called["n"] == 1
