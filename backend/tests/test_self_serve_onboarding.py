"""Self-serve signup: create a pending tenant, card-on-file trial checkout, and
number provisioning on checkout completion. Handlers resolve helpers by module,
so patches target the owning modules."""

from unittest.mock import MagicMock

import config_service
import database
import deps
from routers import billing
from routers import business as biz


# --- create-business endpoint -------------------------------------------------

def test_create_business_makes_pending_tenant_and_links_owner(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(database, "db_tenant_membership_tenant_ids", lambda uid: [])
    monkeypatch.setattr(database, "db_tenant_get_by_client_id", lambda cid: None)
    monkeypatch.setattr(
        database,
        "db_tenant_create_pending",
        lambda cid, name, plan, bv: {
            "id": "t1", "client_id": cid, "name": name, "plan": plan, "twilio_phone_number": None
        },
    )
    monkeypatch.setattr(database, "set_request_client_id", lambda cid: None)
    monkeypatch.setattr(config_service, "_default_client_config_data", lambda cid, plan: {})
    monkeypatch.setattr(config_service, "save_raw_client_config", lambda cid, data: None)
    linked = {}
    monkeypatch.setattr(database, "db_tenant_member_set_single", lambda uid, tid: linked.update(member=(uid, tid)) or True)
    monkeypatch.setattr(deps, "_clerk_patch_user_tenant_metadata", lambda uid, tid: linked.update(clerk=(uid, tid)) or True)
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)

    out = biz.api_create_business(
        biz.CreateBusinessRequest(name="Acme Salon", plan="starter"),
        request=MagicMock(),
        user_id="user_1",
    )
    assert out["already_existed"] is False
    assert out["tenant"]["twilio_phone_number"] is None  # number comes after payment
    assert out["tenant"]["client_id"] == "acme-salon"    # slugified
    assert linked["member"] == ("user_1", "t1")
    assert linked["clerk"] == ("user_1", "t1")


def test_create_business_is_one_per_user(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(database, "db_tenant_membership_tenant_ids", lambda uid: ["t9"])
    monkeypatch.setattr(database, "db_tenant_get_by_id", lambda tid: {"id": "t9", "client_id": "x"})
    created = {"n": 0}
    monkeypatch.setattr(database, "db_tenant_create_pending", lambda *a, **k: created.update(n=created["n"] + 1))

    out = biz.api_create_business(
        biz.CreateBusinessRequest(name="Whatever", plan="growth"),
        request=MagicMock(),
        user_id="user_1",
    )
    assert out["already_existed"] is True
    assert out["tenant"]["id"] == "t9"
    assert created["n"] == 0  # never created a second tenant


# --- checkout trial gating ----------------------------------------------------

def _wire_stripe(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_STARTER_PRICE_ID", "price_123")
    fake = MagicMock()
    fake.checkout.Session.create.return_value = MagicMock(url="https://checkout.example")
    monkeypatch.setattr(billing, "stripe", fake)
    monkeypatch.setattr(billing, "STRIPE_AVAILABLE", True)
    return fake


def test_checkout_gives_trial_to_pending_tenant(monkeypatch):
    fake = _wire_stripe(monkeypatch)
    tenant = {"id": "t1", "client_id": "x", "stripe_customer_id": "cus_1", "twilio_phone_number": None}
    out = billing.create_checkout_session(
        billing.CreateCheckoutSessionRequest(plan="starter", area_code="415"), tenant=tenant
    )
    assert out["url"] == "https://checkout.example"
    kwargs = fake.checkout.Session.create.call_args.kwargs
    assert kwargs["subscription_data"]["trial_period_days"] == 7
    assert kwargs["metadata"]["area_code"] == "415"


def test_checkout_no_trial_for_existing_tenant(monkeypatch):
    fake = _wire_stripe(monkeypatch)
    tenant = {"id": "t2", "client_id": "y", "stripe_customer_id": "cus_2", "twilio_phone_number": "+15551112222"}
    billing.create_checkout_session(
        billing.CreateCheckoutSessionRequest(plan="starter"), tenant=tenant
    )
    kwargs = fake.checkout.Session.create.call_args.kwargs
    assert "trial_period_days" not in kwargs["subscription_data"]


# --- provisioning on checkout completion --------------------------------------

def test_provision_sets_number_on_success(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.com")
    import twilio_provision
    monkeypatch.setattr(
        twilio_provision, "purchase_number",
        lambda **k: {"ok": True, "phone_e164": "+15551230000", "messaging_service_enrolled": True},
    )
    saved = {}
    monkeypatch.setattr(database, "db_tenant_set_twilio_phone", lambda tid, phone: saved.update(tid=tid, phone=phone) or True)
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)

    billing._provision_number_for_tenant({"id": "t1", "client_id": "x"}, area_code="415", request=MagicMock())
    assert saved == {"tid": "t1", "phone": "+15551230000"}


def test_provision_failure_does_not_set_number(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.com")
    import twilio_provision
    monkeypatch.setattr(twilio_provision, "purchase_number", lambda **k: {"ok": False, "errors": ["no_available_numbers"]})
    called = {"n": 0}
    monkeypatch.setattr(database, "db_tenant_set_twilio_phone", lambda tid, phone: called.update(n=called["n"] + 1))
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)

    billing._provision_number_for_tenant({"id": "t1", "client_id": "x"}, area_code=None, request=MagicMock())
    assert called["n"] == 0  # no number written on failure
