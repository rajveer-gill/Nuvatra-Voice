"""The admin screen must read Stripe, not our copy of it.

subscription_status in our database is a copy maintained by webhooks. When a webhook
silently fails — as one did, crashing on an UnboundLocalError while returning 200 to
Stripe — that column is wrong in exactly the moment an admin goes looking: a customer
who has been charged while the app still asks them to choose a plan. Showing our own
column back would confirm the mistake rather than expose it.
"""

from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

import database
import runtime
from routers import admin


class _Sub:
    def __init__(self, status="active", trial_end=None, period_end=1786000000, cancel=False):
        self.status = status
        self.trial_end = trial_end
        self.current_period_end = period_end
        self.cancel_at_period_end = cancel


def _stripe(monkeypatch, sub=None, raises=None, key="sk_live_x"):
    mod = types.SimpleNamespace(api_key=None)

    class _Subscription:
        @staticmethod
        def retrieve(sub_id):
            if raises:
                raise raises
            return sub

    mod.Subscription = _Subscription
    monkeypatch.setitem(sys.modules, "stripe", mod)
    monkeypatch.setenv("STRIPE_SECRET_KEY", key)


def _tenant(monkeypatch, **over):
    row = {"id": "t1", "stripe_subscription_id": "sub_1", "subscription_status": "trialing"}
    row.update(over)
    monkeypatch.setattr(runtime, "USE_DB", True)
    monkeypatch.setattr(admin.runtime, "USE_DB", True)
    monkeypatch.setattr(database, "db_tenant_get_by_id", lambda tid: row if tid == "t1" else None)
    monkeypatch.setattr(admin.database, "db_tenant_get_by_id", lambda tid: row if tid == "t1" else None)


def test_a_disagreement_is_reported_as_out_of_sync(monkeypatch):
    """The real case: Stripe converted the trial and charged; our column still said
    trialing because the webhook crashed."""
    _tenant(monkeypatch, subscription_status="trialing")
    _stripe(monkeypatch, sub=_Sub(status="active"))
    out = admin.admin_tenant_stripe_status("t1", admin_user_id="admin")
    assert out["ours"] == "trialing"
    assert out["stripe"] == "active"
    assert out["in_sync"] is False


def test_agreement_is_reported_as_in_sync(monkeypatch):
    _tenant(monkeypatch, subscription_status="active")
    _stripe(monkeypatch, sub=_Sub(status="active"))
    out = admin.admin_tenant_stripe_status("t1", admin_user_id="admin")
    assert out["in_sync"] is True


def test_a_pending_cancellation_is_surfaced(monkeypatch):
    """Whether the next renewal will charge is the thing an admin is deciding on."""
    _tenant(monkeypatch, subscription_status="active")
    _stripe(monkeypatch, sub=_Sub(status="active", cancel=True))
    out = admin.admin_tenant_stripe_status("t1", admin_user_id="admin")
    assert out["cancel_at_period_end"] is True
    assert out["current_period_end"]


def test_no_subscription_says_so_plainly(monkeypatch):
    _tenant(monkeypatch, stripe_subscription_id="")
    out = admin.admin_tenant_stripe_status("t1", admin_user_id="admin")
    assert out["has_subscription"] is False
    assert out["in_sync"] is None
    assert "No Stripe subscription" in out["message"]


def test_a_stripe_outage_never_breaks_the_admin_screen(monkeypatch):
    """This panel is where you go when billing is already broken; it has to render."""
    _tenant(monkeypatch)
    _stripe(monkeypatch, raises=RuntimeError("stripe down"))
    out = admin.admin_tenant_stripe_status("t1", admin_user_id="admin")
    assert out["stripe"] is None
    assert out["in_sync"] is None
    assert "Could not read Stripe" in out["message"]


def test_a_missing_key_is_named_not_guessed(monkeypatch):
    _tenant(monkeypatch)
    _stripe(monkeypatch, sub=_Sub(), key="")
    out = admin.admin_tenant_stripe_status("t1", admin_user_id="admin")
    assert "STRIPE_SECRET_KEY is not set" in out["message"]


def test_an_unknown_tenant_is_404(monkeypatch):
    _tenant(monkeypatch)
    with pytest.raises(HTTPException) as e:
        admin.admin_tenant_stripe_status("nope", admin_user_id="admin")
    assert e.value.status_code == 404


# --- Granting time off must actually stop the invoice -------------------------
# "Extend trial" and "Give N months free" wrote only our own columns, so a customer
# with a live subscription was told they were exempt and charged anyway on renewal.
# Stripe's own trial_end is the mechanism: while it is in the future Stripe does not
# invoice, and normal billing resumes afterwards on its own.


def test_granting_time_pushes_the_stripe_trial(monkeypatch):
    seen = {}

    mod = types.SimpleNamespace(api_key=None)

    class _Subscription:
        @staticmethod
        def modify(sub_id, **kw):
            seen["sub_id"] = sub_id
            seen.update(kw)
            return _Sub()

    mod.Subscription = _Subscription
    monkeypatch.setitem(sys.modules, "stripe", mod)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_x")

    from datetime import datetime, timezone

    until = datetime(2026, 12, 1, tzinfo=timezone.utc)
    out = admin._defer_stripe_billing({"stripe_subscription_id": "sub_9"}, until)
    assert out["applied"] is True
    assert seen["sub_id"] == "sub_9"
    assert seen["trial_end"] == int(until.timestamp())
    # Deferring billing must not credit or invoice the part-period.
    assert seen["proration_behavior"] == "none"


def test_a_tenant_with_no_subscription_is_not_an_error(monkeypatch):
    from datetime import datetime, timezone

    out = admin._defer_stripe_billing({}, datetime(2026, 12, 1, tzinfo=timezone.utc))
    assert out["applied"] is False
    assert out["reason"] == "no_subscription"
    assert out["error"] is None


def test_a_stripe_failure_is_reported_not_swallowed(monkeypatch):
    """The whole claim being made is "they won't be charged". If Stripe refused, the
    admin has to find out now, not on the customer's next statement."""
    mod = types.SimpleNamespace(api_key=None)

    class _Subscription:
        @staticmethod
        def modify(sub_id, **kw):
            raise RuntimeError("card_declined")

    mod.Subscription = _Subscription
    monkeypatch.setitem(sys.modules, "stripe", mod)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_x")

    from datetime import datetime, timezone

    out = admin._defer_stripe_billing(
        {"stripe_subscription_id": "sub_9"}, datetime(2026, 12, 1, tzinfo=timezone.utc)
    )
    assert out["applied"] is False
    assert out["reason"] == "stripe_error"
    assert "card_declined" in out["error"]


def test_a_missing_key_does_not_look_like_success(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    from datetime import datetime, timezone

    out = admin._defer_stripe_billing(
        {"stripe_subscription_id": "sub_9"}, datetime(2026, 12, 1, tzinfo=timezone.utc)
    )
    assert out["applied"] is False
    assert out["reason"] == "not_configured"
