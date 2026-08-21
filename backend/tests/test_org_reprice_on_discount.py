"""A partner rate must reach a group that already subscribed.

Staging showed the gap: the discounted prices were created and saved, the admin
was told "$50 off each store", and the subscription went on billing list price
because nothing repointed it. Adding a second store made it worse — quantity
went to 2 on the undiscounted price, so the group paid 2x list.
"""
import pytest
import stripe
from stripe import StripeObject

import routers.billing as billing


def _obj(**fields):
    o = StripeObject()
    for k, v in fields.items():
        setattr(o, k, v)
    return o


def _sub(item_id="si_1", price_id="price_list", qty=1):
    return _obj(items=_obj(data=[_obj(id=item_id, quantity=qty, price=_obj(id=price_id))]))


@pytest.fixture
def org_on_list_price(monkeypatch):
    org = {
        "id": "org_1",
        "plan": "starter",
        "stripe_subscription_id": "sub_1",
        "price_overrides": {"starter": "price_partner"},
    }
    monkeypatch.setattr(billing.runtime, "USE_DB", True, raising=False)
    monkeypatch.setattr(billing.database, "db_org_get_by_id", lambda _i: org)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    return org


def test_subscription_line_exposes_its_price(monkeypatch):
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda *a, **k: _sub(qty=2))
    line = billing._org_subscription_line("sub_1")
    assert line == {"item_id": "si_1", "quantity": 2, "price_id": "price_list"}


def test_existing_subscription_is_moved_onto_the_partner_price(org_on_list_price, monkeypatch):
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda *a, **k: _sub(qty=2))
    seen = {}

    def _modify(sub_id, **kw):
        seen["sub_id"] = sub_id
        seen.update(kw)
        return _obj(id=sub_id)

    monkeypatch.setattr(stripe.Subscription, "modify", _modify)
    out = billing.move_org_subscription_to_price("org_1")
    assert out["repriced"] is True
    assert out["from_price"] == "price_list"
    assert out["to_price"] == "price_partner"
    assert seen["items"] == [{"id": "si_1", "price": "price_partner"}]
    # No retroactive credit for the part of the period already paid.
    assert seen["proration_behavior"] == "none"


def test_repricing_leaves_quantity_alone(org_on_list_price, monkeypatch):
    """Quantity is the store count and is owned by the store-sync path. Repricing
    must not reset it to 1 and quietly halve the bill."""
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda *a, **k: _sub(qty=7))
    seen = {}
    monkeypatch.setattr(stripe.Subscription, "modify",
                        lambda sub_id, **kw: seen.update(kw) or _obj(id=sub_id))
    billing.move_org_subscription_to_price("org_1")
    assert "quantity" not in seen["items"][0]


def test_no_stripe_call_when_already_on_the_price(org_on_list_price, monkeypatch):
    monkeypatch.setattr(stripe.Subscription, "retrieve",
                        lambda *a, **k: _sub(price_id="price_partner"))

    def _boom(*a, **k):
        raise AssertionError("must not modify a subscription that is already correct")

    monkeypatch.setattr(stripe.Subscription, "modify", _boom)
    out = billing.move_org_subscription_to_price("org_1")
    assert out["repriced"] is False
    assert out["reason"] == "already_on_price"


def test_group_without_a_subscription_is_a_clean_noop(monkeypatch):
    monkeypatch.setattr(billing.runtime, "USE_DB", True, raising=False)
    monkeypatch.setattr(billing.database, "db_org_get_by_id",
                        lambda _i: {"id": "org_2", "plan": "starter",
                                    "stripe_subscription_id": ""})
    out = billing.move_org_subscription_to_price("org_2")
    assert out == {"repriced": False, "reason": "no_subscription",
                   "from_price": None, "to_price": None}


def test_clearing_the_override_moves_them_back_to_list(monkeypatch):
    """Symmetry: if apply repriced them, clear has to reprice them back."""
    org = {"id": "org_3", "plan": "starter", "stripe_subscription_id": "sub_3",
           "price_overrides": None}
    monkeypatch.setattr(billing.runtime, "USE_DB", True, raising=False)
    monkeypatch.setattr(billing.database, "db_org_get_by_id", lambda _i: org)
    monkeypatch.setattr(billing, "_stripe_price_id", lambda plan: "price_list")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setattr(stripe.Subscription, "retrieve",
                        lambda *a, **k: _sub(price_id="price_partner"))
    seen = {}
    monkeypatch.setattr(stripe.Subscription, "modify",
                        lambda sub_id, **kw: seen.update(kw) or _obj(id=sub_id))
    out = billing.move_org_subscription_to_price("org_3")
    assert out["repriced"] is True
    assert seen["items"] == [{"id": "si_1", "price": "price_list"}]


def test_stripe_failure_is_reported_not_raised(org_on_list_price, monkeypatch):
    """The override is already saved by this point; a Stripe hiccup must not read
    to the admin as 'the discount did not save'."""
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda *a, **k: _sub())

    def _boom(*a, **k):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(stripe.Subscription, "modify", _boom)
    out = billing.move_org_subscription_to_price("org_1")
    assert out["repriced"] is False
    assert "stripe down" in (out["reason"] or "")
