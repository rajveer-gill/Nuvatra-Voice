"""Call recording is gated by env flag AND Pro plan (via get_plan_limits)."""
import os
from datetime import datetime, timedelta, timezone

import pytest

import main


def _future_iso():
    return (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()


@pytest.mark.parametrize(
    "tenant,env_on,expected",
    [
        ({"plan": "pro", "subscription_status": "active"}, True, True),
        ({"plan": "pro", "subscription_status": "active"}, False, False),
        ({"plan": "growth", "subscription_status": "active"}, True, False),
        ({"plan": "starter", "subscription_status": "active"}, True, False),
        (
            {"plan": "free", "subscription_status": "trialing", "trial_ends_at": _future_iso()},
            True,
            True,
        ),
    ],
)
def test_call_recording_enabled_for_tenant(monkeypatch, tenant, env_on, expected):
    monkeypatch.setenv("CALL_RECORDING_ENABLED", "true" if env_on else "false")
    assert main._call_recording_enabled_for_tenant(tenant) is expected
