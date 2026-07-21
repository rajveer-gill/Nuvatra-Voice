"""Card-free demo accounts: access, seeded data, and the activation purge.

The purge is the dangerous half of this feature — it deletes by client_id — so
most of what's here is about proving it can only ever fire against a tenant whose
data was never real.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

import config_service
import demo_seed
from plans import get_plan_limits
from subscription_access import get_tenant_subscription_state, webhook_access_denial_reason


def _demo_tenant(**overrides) -> dict:
    """A tenant shaped the way POST /api/onboarding/start-demo leaves it."""
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "client_id": "demo-shop",
        "name": "Demo Shop",
        # The load-bearing detail: no number means no call can route here.
        "twilio_phone_number": None,
        "plan": "pro",
        "subscription_status": "incomplete",
        "trial_ends_at": None,
        "billing_exempt_until": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
        "demo_mode": True,
        "account_paused": False,
    }
    base.update(overrides)
    return base


# --- Access -------------------------------------------------------------------


def test_demo_tenant_can_use_app():
    """A demo tenant is 'incomplete' with no trial, so its access must come from the
    billing exemption alone — otherwise the dashboard locks them out."""
    state = get_tenant_subscription_state(_demo_tenant())
    assert state["can_use_app"] is True
    assert state["demo_mode"] is True


def test_demo_tenant_gets_pro_tier_features():
    """The demo should show the whole product, not a starter subset."""
    limits = get_plan_limits(_demo_tenant())
    assert limits["has_call_recording"] is True
    assert limits["has_lead_capture"] is True
    assert limits["has_messages"] is True


def test_demo_trial_clock_has_not_started():
    """The 7-day trial must not begin until a card does — create-checkout-session keys
    `needs_trial` off the missing number, so a demo tenant still gets its full trial."""
    tenant = _demo_tenant()
    assert tenant["trial_ends_at"] is None
    assert tenant["subscription_status"] != "trialing"
    assert not (tenant.get("twilio_phone_number") or "").strip()


def test_expired_demo_loses_access():
    """When the demo window lapses the exemption is the only grant, so access stops."""
    state = get_tenant_subscription_state(
        _demo_tenant(billing_exempt_until=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    )
    assert state["can_use_app"] is False


def test_paused_demo_is_denied():
    """The admin kill-switch must still beat a demo exemption."""
    state = get_tenant_subscription_state(_demo_tenant(account_paused=True))
    assert state["can_use_app"] is False


def test_demo_mode_defaults_false_for_normal_tenant():
    state = get_tenant_subscription_state(
        {"client_id": "real", "subscription_status": "active", "plan": "starter"}
    )
    assert state["demo_mode"] is False


def test_demo_tenant_can_never_serve_a_live_call():
    """Two independent guards. A demo tenant has no number, so no webhook can resolve
    it; and even if one somehow did (a number attached by hand from the admin console),
    the access gate declines rather than reading sample services to a real caller."""
    assert not (_demo_tenant().get("twilio_phone_number") or "")
    assert webhook_access_denial_reason(_demo_tenant()) == "demo_account"


def test_webhook_gate_still_allows_a_real_paid_tenant():
    """The demo backstop must not deny anyone real."""
    assert webhook_access_denial_reason(
        {"client_id": "real", "subscription_status": "active", "plan": "pro"}
    ) is None


# --- Seeded sample data -------------------------------------------------------


def test_demo_phone_numbers_stay_in_the_fiction_block():
    """Sample numbers are shown to prospects and are click-to-call in the UI, so they
    must never be dialable strangers."""
    for n in (100, 115, 199):
        assert demo_seed._fake_phone(n).startswith("+1415555")
    for bad in (99, 200, 0):
        with pytest.raises(ValueError):
            demo_seed._fake_phone(bad)


def test_demo_config_is_populated_and_marked():
    cfg = demo_seed.demo_config("demo-shop", "Rajveer's Cuts")
    assert cfg["business_name"] == "Rajveer's Cuts"
    assert cfg["is_demo_data"] is True
    assert len(cfg["services"]) >= 3
    assert len(cfg["staff"]) >= 2
    assert cfg["forwarding_phone"] == demo_seed._DEMO_SHOP_PHONE


def test_demo_staff_only_offer_services_that_exist():
    """A stylist mapped to a service id that isn't in the list would break booking."""
    cfg = demo_seed.demo_config("demo-shop", "Shop")
    service_ids = {s["id"] for s in cfg["services"]}
    for member in cfg["staff"]:
        assert set(member["service_ids"]) <= service_ids


# --- Activation purge ---------------------------------------------------------


def test_purge_never_runs_for_a_non_demo_tenant(monkeypatch):
    """The single most important guard: a paying tenant's checkout event must not
    reach the delete path at all."""
    from routers import billing

    called = []
    monkeypatch.setattr(
        billing.database, "db_tenant_deactivate_demo", lambda *a, **k: called.append(a)
    )
    billing._deactivate_demo_if_needed({"id": "x", "client_id": "real-shop", "demo_mode": False}, "pro")
    billing._deactivate_demo_if_needed({"id": "x", "client_id": "real-shop"}, "pro")
    assert called == []


def test_activation_clears_sample_services_and_keeps_number_choice(monkeypatch):
    """Sample services must not survive activation (a live receptionist would quote
    them), but the prospect's real number_mode answer must."""
    from routers import billing

    captured = {}

    def fake_deactivate(tenant_id, replacement_config=None):
        captured["config"] = replacement_config
        return {"client_id": "demo-shop", "deleted": {"call_log": 40}}

    monkeypatch.setattr(billing.database, "db_tenant_deactivate_demo", fake_deactivate)
    # billing imports config_service inside the function, but it's the same module
    # object, so patching the attribute here reaches it.
    monkeypatch.setattr(
        config_service,
        "_read_raw_client_config",
        lambda cid: {
            "number_mode": "existing",
            "existing_business_number": "+14155550199",
            "services": demo_seed.SAMPLE_SERVICES,
            "staff": demo_seed.SAMPLE_STAFF,
        },
    )
    monkeypatch.setattr(config_service, "save_raw_client_config", lambda *a, **k: None)
    monkeypatch.setattr(billing.deps, "audit_log", lambda *a, **k: None)

    billing._deactivate_demo_if_needed(
        {"id": "t1", "client_id": "demo-shop", "name": "Rajveer's Cuts", "demo_mode": True}, "growth"
    )

    cfg = captured["config"]
    assert cfg is not None
    assert cfg["services"] == []          # sample services gone
    assert cfg["staff"] == []             # sample stylists gone
    assert cfg["number_mode"] == "existing"          # real answer kept
    assert cfg["existing_business_number"] == "+14155550199"
    assert cfg["business_name"] == "Rajveer's Cuts"


def test_activation_is_safe_on_stripe_redelivery(monkeypatch):
    """Stripe redelivers events. The second pass finds demo_mode already false, so the
    claim returns None and nothing further should happen — including no audit entry."""
    from routers import billing

    audits = []
    monkeypatch.setattr(billing.database, "db_tenant_deactivate_demo", lambda *a, **k: None)
    monkeypatch.setattr(config_service, "_read_raw_client_config", lambda cid: {})
    monkeypatch.setattr(config_service, "save_raw_client_config", lambda *a, **k: None)
    monkeypatch.setattr(billing.deps, "audit_log", lambda *a, **k: audits.append(a))

    billing._deactivate_demo_if_needed(
        {"id": "t1", "client_id": "demo-shop", "name": "Shop", "demo_mode": True}, "pro"
    )
    assert audits == []


def test_activation_failure_does_not_break_the_webhook(monkeypatch):
    """A raise here would make Stripe retry the whole event forever, and would strand
    number provisioning that runs after it."""
    from routers import billing

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(billing.database, "db_tenant_deactivate_demo", boom)
    monkeypatch.setattr(config_service, "_read_raw_client_config", lambda cid: {})
    billing._deactivate_demo_if_needed(
        {"id": "t1", "client_id": "demo-shop", "name": "Shop", "demo_mode": True}, "pro"
    )  # must not raise


# --- Real-Postgres integration ------------------------------------------------

_DB = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL required (needs real Postgres)"
)


@_DB
def test_seed_then_purge_round_trip():
    """End-to-end against Postgres: seeding fills the tenant, activation empties it,
    and a second activation is a no-op."""
    import database

    database.init_db()
    tenant = database.db_tenant_create_pending("demo-rt", "Round Trip Salon", "pro", "salon_chair")
    assert tenant
    database.db_tenant_set_demo_mode(tenant["id"], True)

    counts = demo_seed.seed_demo_tenant("demo-rt", "Round Trip Salon")
    assert counts["calls"] > 0
    assert counts["appointments"] > 0

    database.set_request_client_id("demo-rt")
    assert len(database.db_call_log_load()) == counts["calls"]

    res = database.db_tenant_deactivate_demo(tenant["id"], {"client_id": "demo-rt", "services": []})
    assert res is not None
    assert res["deleted"]["call_log"] == counts["calls"]

    database.set_request_client_id("demo-rt")
    assert database.db_call_log_load() == []
    assert database.db_messages_get_all() == []

    fresh = database.db_tenant_get_by_id(tenant["id"])
    assert fresh["demo_mode"] is False
    assert fresh["billing_exempt_until"] is None

    # Redelivery: already converted, so nothing is claimed.
    assert database.db_tenant_deactivate_demo(tenant["id"], {"client_id": "demo-rt"}) is None


@_DB
def test_purge_only_touches_the_demo_tenant():
    """The delete is by client_id — prove a neighbouring tenant's rows survive."""
    import database

    database.init_db()
    demo = database.db_tenant_create_pending("demo-iso", "Demo Iso", "pro", "salon_chair")
    database.db_tenant_set_demo_mode(demo["id"], True)
    demo_seed.seed_demo_tenant("demo-iso", "Demo Iso")

    database.set_request_client_id("real-iso")
    database.db_messages_insert(
        {"caller_name": "Real Customer", "caller_phone": "+14155551234", "message": "real"},
        client_id="real-iso",
    )

    database.db_tenant_deactivate_demo(demo["id"], {"client_id": "demo-iso"})

    database.set_request_client_id("real-iso")
    assert len(database.db_messages_get_all()) == 1
