"""A DB-backed deployment must refuse to boot if auth/webhook secrets are
missing or a legacy CLIENT_ID is set — a missing env var must never silently
disable authentication."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import main

_GOOD = {
    "DATABASE_URL": "postgres://x",
    "CLERK_JWKS_URL": "https://clerk/jwks",
    "CLERK_ISSUER": "https://clerk",
    "CLERK_AUDIENCE": "aud",
    "TWILIO_AUTH_TOKEN": "tok",
    "CLIENT_ID": "",
    "ALLOW_INSECURE_WEBHOOKS": "",
}


def _env(**overrides):
    e = dict(_GOOD)
    e.update(overrides)
    return e


def test_fully_configured_prod_boots():
    with patch.dict("os.environ", _env(), clear=True):
        main._assert_secure_production_config()  # must not raise


def test_local_dev_without_db_is_skipped():
    with patch.dict("os.environ", {"DATABASE_URL": ""}, clear=True):
        main._assert_secure_production_config()  # no DB → not production


def test_allow_insecure_webhooks_bypasses_guard():
    with patch.dict(
        "os.environ",
        _env(CLERK_JWKS_URL="", TWILIO_AUTH_TOKEN="", ALLOW_INSECURE_WEBHOOKS="1"),
        clear=True,
    ):
        main._assert_secure_production_config()  # explicit dev opt-out


@pytest.mark.parametrize(
    "override",
    [
        {"CLERK_JWKS_URL": ""},
        {"CLERK_ISSUER": ""},
        {"CLERK_AUDIENCE": ""},
        {"TWILIO_AUTH_TOKEN": ""},
        {"CLIENT_ID": "legacy-tenant"},
    ],
)
def test_misconfigured_prod_refuses_to_boot(override):
    with patch.dict("os.environ", _env(**override), clear=True):
        with pytest.raises(RuntimeError):
            main._assert_secure_production_config()
