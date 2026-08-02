"""Org-level billing: one subscription covering N stores, and who may provision them.

The money claims under test: a store in a paying group is live without a card of its
own, an independent store is untouched by any of this, and a cancelled group takes
its stores down with it.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

import database
import subscription_access
from plans import get_plan_limits
from subscription_access import evaluate_billing, get_tenant_subscription_state


def _future():
    return (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()


def _past():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _org_store(**overrides) -> dict:
    """A store created inside a group: no card, no trial of its own, org_id set."""
    base = {
        "id": "22222222-2222-2222-2222-222222222222",
        "client_id": "org-shop",
        "name": "Supercuts Downtown",
        "twilio_phone_number": None,
        "plan": "pro",
        "subscription_status": "incomplete",
        "trial_ends_at": None,
        "billing_exempt_until": None,
        "account_paused": False,
        "demo_mode": False,
        "org_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    }
    base.update(overrides)
    return base


def _paying_org(**overrides) -> dict:
    base = {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "name": "Supercuts North",
        "plan": "pro",
        "subscription_status": "active",
        "trial_ends_at": None,
        "billing_exempt_until": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def org_billing(monkeypatch):
    """Point the org lookup at a dict instead of the DB."""

    def _set(org):
        monkeypatch.setattr(subscription_access, "_load_org_billing", lambda oid: org)

    return _set


# --- evaluate_billing is shared by tenants and orgs ----------------------------


def test_evaluate_billing_treats_org_and_tenant_identically():
    """Both carry the same billing columns; if these ever diverge a group and a store
    would be judged by different rules."""
    row = {"subscription_status": "active"}
    assert evaluate_billing(row)["active"] is True
    assert evaluate_billing({"subscription_status": "incomplete"})["active"] is False
    assert evaluate_billing({"subscription_status": "trialing", "trial_ends_at": _future()})["active"] is True
    assert evaluate_billing({"subscription_status": "trialing", "trial_ends_at": _past()})["active"] is False
    assert evaluate_billing({"billing_exempt_until": _future()})["active"] is True


def test_trialing_with_no_end_date_is_open_ended():
    assert evaluate_billing({"subscription_status": "trialing"})["trial_active"] is True


def test_unparseable_trial_date_fails_open():
    """Long-standing behaviour, pinned: never lock a trialing customer out over a bad
    timestamp."""
    assert evaluate_billing({"subscription_status": "trialing", "trial_ends_at": "garbage"})["active"] is True


# --- Inheritance --------------------------------------------------------------


def test_store_is_live_on_the_groups_subscription(org_billing):
    """The point of the whole feature: she pays once, her stores work."""
    org_billing(_paying_org())
    state = get_tenant_subscription_state(_org_store())
    assert state["can_use_app"] is True
    assert state["billing_source"] == "org"


def test_store_without_a_group_still_needs_its_own_billing(org_billing):
    """An ordinary store must be unaffected by any of this."""
    org_billing(None)
    state = get_tenant_subscription_state(_org_store(org_id=None))
    assert state["can_use_app"] is False


def test_cancelled_group_takes_its_stores_down(org_billing):
    org_billing(_paying_org(subscription_status="canceled"))
    assert get_tenant_subscription_state(_org_store())["can_use_app"] is False


def test_expired_group_trial_takes_its_stores_down(org_billing):
    org_billing(_paying_org(subscription_status="trialing", trial_ends_at=_past()))
    assert get_tenant_subscription_state(_org_store())["can_use_app"] is False


def test_group_trial_covers_its_stores(org_billing):
    org_billing(_paying_org(subscription_status="trialing", trial_ends_at=_future()))
    assert get_tenant_subscription_state(_org_store())["can_use_app"] is True


def test_comped_group_covers_its_stores(org_billing):
    """Invoice-and-comp: an exemption on the group works like it does on a tenant."""
    org_billing(_paying_org(subscription_status="incomplete", billing_exempt_until=_future()))
    assert get_tenant_subscription_state(_org_store())["can_use_app"] is True


def test_paused_store_stays_paused_inside_a_paying_group(org_billing):
    """The admin kill-switch must not be escapable by joining a group."""
    org_billing(_paying_org())
    state = get_tenant_subscription_state(_org_store(account_paused=True))
    assert state["can_use_app"] is False


def test_store_paying_for_itself_does_not_hit_the_org(monkeypatch):
    """Inheritance is a fallback, not a lookup on every request — a store that stands
    on its own must not cost an extra query."""
    calls = []
    monkeypatch.setattr(
        subscription_access, "_load_org_billing", lambda oid: calls.append(oid) or None
    )
    state = get_tenant_subscription_state(_org_store(subscription_status="active"))
    assert state["can_use_app"] is True
    assert state["billing_source"] == "own"
    assert calls == []


def test_trial_on_the_org_grants_pro_features_to_its_store(monkeypatch):
    """The 7-day trial is meant to unlock everything. It lives on the ORG (the store's
    own subscription_status stays 'incomplete'), so reading only the tenant made a
    trialing customer see "PRO FEATURE — upgrade your plan" on Messages.
    """
    import plans

    org = {
        "id": "org-1",
        "plan": "starter",
        "subscription_status": "trialing",
        "trial_ends_at": _future(),
    }
    monkeypatch.setattr(plans, "_billing_row_for_limits", lambda t: org)

    limits = plans.get_plan_limits(_org_store(plan="starter"))
    assert limits["is_trial"] is True
    # Everything a trial is supposed to include, even on a starter plan.
    assert limits["has_messages"] is True
    assert limits["has_lead_capture"] is True
    assert limits["has_call_recording"] is True
    assert limits["minutes_cap"] == 3500


def test_expired_org_trial_drops_the_store_to_its_paid_tier():
    """Once the trial ends they get what they actually bought — not Pro forever."""
    import plans

    limits = plans.get_plan_limits(
        {"plan": "starter", "subscription_status": "trialing", "trial_ends_at": _past()}
    )
    assert limits["is_trial"] is False
    assert limits["has_messages"] is False


def test_a_store_that_pays_for_itself_never_looks_up_an_org(monkeypatch):
    """get_plan_limits runs on the voice path — it must not add a query per call for
    tenants that can answer on their own."""
    import plans

    calls = []
    monkeypatch.setattr(
        plans, "_is_trial_active", lambda t: bool(t) and t.get("subscription_status") == "trialing"
    )

    import database

    monkeypatch.setattr(
        database, "db_org_get_by_id", lambda oid: calls.append(oid) or None
    )
    plans.get_plan_limits({"plan": "pro", "subscription_status": "active", "org_id": "org-1"})
    assert calls == [], "an active tenant must resolve without touching its org"


def test_org_store_gets_the_tier_the_group_paid_for(org_billing):
    """get_plan_limits only ever reads the tenant's own plan, which is why the store's
    plan column is stamped with the org's at creation."""
    org_billing(_paying_org())
    limits = get_plan_limits(_org_store(plan="pro"))
    assert limits["has_call_recording"] is True
    assert limits["minutes_cap"] == 3500


# --- Real-Postgres integration ------------------------------------------------

_DB = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL required (needs real Postgres)"
)


@_DB
def test_store_inherits_real_org_billing_end_to_end(monkeypatch):
    """No mocks: a store created in a paying group is live straight out of the DB.

    runtime.USE_DB has to be on for the org lookup to run at all — database.init_db()
    doesn't set it (main.py does, at startup), so the flag is forced here. Without it
    _load_org_billing short-circuits to None and the store looks unpaid.
    """
    import runtime

    database.init_db()
    monkeypatch.setattr(runtime, "USE_DB", True)
    org = database.db_org_create("Supercuts North")
    database.db_org_update_subscription(org["id"], subscription_status="active", plan="pro")
    t = database.db_tenant_create_pending("inherit-shop", "Downtown", "pro", "salon_chair")
    database.db_org_attach_tenant(t["id"], org["id"])

    fresh = database.db_tenant_get_by_id(t["id"])
    assert fresh["org_id"] == org["id"]  # _row_to_tenant must surface it or nothing works
    assert fresh["subscription_status"] == "incomplete"  # never paid for itself
    assert get_tenant_subscription_state(fresh)["can_use_app"] is True


@_DB
def test_store_count_drives_the_quantity():
    database.init_db()
    org = database.db_org_create("Region")
    assert database.db_org_store_count(org["id"]) == 0
    for i in range(3):
        t = database.db_tenant_create_pending(f"count-{i}", f"Shop {i}", "pro", "salon_chair")
        database.db_org_attach_tenant(t["id"], org["id"])
    assert database.db_org_store_count(org["id"]) == 3
    # Detaching a store must reduce what they're billed for.
    last = database.db_tenant_get_by_client_id("count-2")
    database.db_org_attach_tenant(last["id"], None)
    assert database.db_org_store_count(org["id"]) == 2


@_DB
def test_plan_sync_stamps_every_store_in_the_group():
    database.init_db()
    org = database.db_org_create("Region")
    for i in range(2):
        t = database.db_tenant_create_pending(f"plan-{i}", f"Shop {i}", "starter", "salon_chair")
        database.db_org_attach_tenant(t["id"], org["id"])
    assert database.db_org_sync_store_plans(org["id"], "pro") == 2
    for i in range(2):
        assert database.db_tenant_get_by_client_id(f"plan-{i}")["plan"] == "pro"


@_DB
def test_plan_sync_does_not_touch_stores_outside_the_group():
    database.init_db()
    org = database.db_org_create("Region")
    inside = database.db_tenant_create_pending("sync-in", "In", "starter", "salon_chair")
    database.db_org_attach_tenant(inside["id"], org["id"])
    database.db_tenant_create_pending("sync-out", "Out", "starter", "salon_chair")

    database.db_org_sync_store_plans(org["id"], "pro")
    assert database.db_tenant_get_by_client_id("sync-out")["plan"] == "starter"


@_DB
def test_org_resolves_from_its_stripe_subscription():
    """Portal-initiated webhooks carry no metadata, so this lookup is the only way to
    know the event is a group's and not a store's."""
    database.init_db()
    org = database.db_org_create("Region")
    database.db_org_update_subscription(org["id"], stripe_subscription_id="sub_org_123")
    found = database.db_org_get_by_stripe_subscription_id("sub_org_123")
    assert found and found["id"] == org["id"]
    assert database.db_org_get_by_stripe_subscription_id("sub_nope") is None


@_DB
def test_partial_billing_update_does_not_blank_other_fields():
    database.init_db()
    org = database.db_org_create("Region")
    database.db_org_update_subscription(
        org["id"], stripe_customer_id="cus_1", subscription_status="active", plan="pro"
    )
    database.db_org_update_subscription(org["id"], subscription_status="past_due")
    after = database.db_org_get_by_id(org["id"])
    assert after["stripe_customer_id"] == "cus_1"
    assert after["plan"] == "pro"
    assert after["subscription_status"] == "past_due"
