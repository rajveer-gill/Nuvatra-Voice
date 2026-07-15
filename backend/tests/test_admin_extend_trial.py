"""Admin extend-trial must restore `trialing` status, not just push the date.

Regression guard for the bug where a tenant that was charged after the trial expired
(subscription_status="active") — or refunded/canceled — kept getting gated to starter-tier
features after an admin "extend trial", because get_plan_limits only grants full pro-tier
trial access when subscription_status == "trialing".
"""
from datetime import datetime, timezone

import pytest

import database
import deps
import runtime
from routers import admin


def test_extend_trial_sets_status_trialing(monkeypatch):
    """Extending a free trial writes subscription_status='trialing' + a future trial_ends_at
    in a single update, so the tenant gets the full (pro-tier) trial experience again."""
    calls = {}

    monkeypatch.setattr(runtime, "USE_DB", True, raising=False)
    # A tenant that already paid (charged after the trial lapsed): status is "active", plan "starter".
    monkeypatch.setattr(
        database,
        "db_tenant_get_by_id",
        lambda tid: {
            "id": tid,
            "client_id": "gills-salons",
            "plan": "starter",
            "subscription_status": "active",
            "trial_ends_at": None,
        },
    )

    def fake_update(tenant_id, **kwargs):
        calls["tenant_id"] = tenant_id
        calls.update(kwargs)
        return True

    monkeypatch.setattr(database, "db_tenant_update_subscription", fake_update)
    # The extend-trial path must NOT use the date-only helper (that's what left status stale).
    monkeypatch.setattr(
        database,
        "db_tenant_extend_trial",
        lambda *a, **k: pytest.fail("extend_trial_months must set status, not push the date only"),
    )
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)

    req = admin.BillingExemptUpdate(extend_trial_months=2)
    result = admin.admin_tenant_billing_exempt(
        tenant_id="t1", req=req, request=None, admin_user_id="admin1"
    )

    assert result["success"] is True
    assert result["subscription_status"] == "trialing"
    assert calls["tenant_id"] == "t1"
    assert calls["subscription_status"] == "trialing"
    assert calls["trial_ends_at"] > datetime.now(timezone.utc)


def test_extend_trial_grants_full_pro_access():
    """End-to-end contract: once status is 'trialing' with a future end date, get_plan_limits
    unlocks the pro-tier features that were locked at starter."""
    from plans import get_plan_limits

    future = datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1)
    tenant = {
        "plan": "starter",
        "subscription_status": "trialing",
        "trial_ends_at": future,
    }
    limits = get_plan_limits(tenant)
    assert limits["is_trial"] is True
    # Features that are False at starter must be unlocked during an active trial.
    assert limits["has_messages"] is True
    assert limits["has_lead_capture"] is True
    assert limits["has_call_recording"] is True
    assert limits["has_export"] is True
