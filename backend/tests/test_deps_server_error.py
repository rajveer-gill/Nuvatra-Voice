"""Regression: routers call deps._server_error(...) on failure.

It lived only in main.py, so every server-error path in admin/appointments/
billing/core/phone raised AttributeError when an exception was actually hit
(observed on a live call: 'module deps has no attribute _server_error').
These tests pin the helper to deps and verify it never leaks the raw exception.
"""

from __future__ import annotations

import importlib

import deps
from fastapi import HTTPException


def test_deps_exposes_server_error():
    assert hasattr(deps, "_server_error")
    assert callable(deps._server_error)


def test_server_error_returns_safe_http_exception():
    err = deps._server_error("context", ValueError("postgres://user:pw@host/db"))
    assert isinstance(err, HTTPException)
    assert err.status_code == 500
    # Must not echo the raw exception (could embed secrets / hostnames).
    assert "postgres" not in str(err.detail)
    assert err.detail == "Internal server error"


def test_server_error_respects_overrides():
    err = deps._server_error(
        "context", RuntimeError("boom"), status_code=503, public_detail="Service unavailable"
    )
    assert err.status_code == 503
    assert err.detail == "Service unavailable"


def test_routers_reference_resolvable_server_error():
    # Importing each router that calls deps._server_error must succeed, and the
    # attribute they reference must resolve (guards against the AttributeError).
    for mod_name in (
        "routers.phone",
        "routers.billing",
        "routers.appointments",
        "routers.core",
        "routers.admin",
    ):
        importlib.import_module(mod_name)
        assert getattr(deps, "_server_error", None) is not None
