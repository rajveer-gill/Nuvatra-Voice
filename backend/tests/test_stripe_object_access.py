"""Stripe responses must be read through _plain(), not .get().

The SDK's objects used to subclass dict; current versions do not, so `.get()` on
anything an API call returns raises AttributeError. requirements.txt had no upper
bound, so a rebuild crossed that line and silently broke partner pricing and the
org subscription-quantity sync — the second of which bills the wrong store count.

These tests build fixtures from the REAL installed StripeObject, so they track
whatever version we actually ship rather than a hand-rolled imitation of it.
"""
import pytest
import stripe
from stripe import StripeObject

import routers.billing as billing


def _obj(**fields):
    """A response shaped like the installed SDK returns."""
    o = StripeObject()
    for k, v in fields.items():
        setattr(o, k, v)
    return o


def test_installed_sdk_still_has_no_dict_get():
    """Guards the premise. If a future pin restores dict subclassing this test
    fails loudly rather than leaving the workaround here unexplained."""
    if isinstance(StripeObject(), dict):
        pytest.skip("SDK subclasses dict again; _plain() is a no-op but still correct")
    assert not hasattr(StripeObject(), "get")


def test_plain_unwraps_nested_stripe_objects():
    nested = _obj(interval="month")
    top = _obj(unit_amount=9900, currency="usd", recurring=nested)
    out = billing._plain(top)
    assert isinstance(out, dict)
    assert out.get("unit_amount") == 9900
    assert out.get("recurring", {}).get("interval") == "month"


def test_org_subscription_item_reads_a_real_sdk_object(monkeypatch):
    """The money bug: a failure here bills an org for the wrong store count."""
    item = _obj(id="si_123", quantity=7)
    sub = _obj(items=_obj(data=[item]))
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda *a, **k: sub)
    assert billing._org_subscription_item("sub_123") == ("si_123", 7)


def test_build_partner_prices_reuses_an_existing_discounted_price(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setattr(billing, "_stripe_price_id", lambda plan: f"price_{plan}_base")
    base = _obj(unit_amount=9900, currency="usd", recurring=_obj(interval="month"),
                product="prod_1")
    existing = _obj(id="price_discounted", unit_amount=4900, currency="usd",
                    recurring=_obj(interval="month"))
    monkeypatch.setattr(stripe.Price, "retrieve", lambda *a, **k: base)
    monkeypatch.setattr(stripe.Price, "list", lambda *a, **k: _obj(data=[existing]))

    def _no_create(*a, **k):
        raise AssertionError("must reuse the existing price, not create a duplicate")

    monkeypatch.setattr(stripe.Price, "create", _no_create)
    out = billing.build_partner_prices(5000)
    assert out.get("_errors") in (None, [])
    assert out["starter"] == "price_discounted"


def test_build_partner_prices_creates_when_absent(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setattr(billing, "_stripe_price_id", lambda plan: f"price_{plan}_base")
    base = _obj(unit_amount=9900, currency="usd", recurring=_obj(interval="month"),
                product="prod_1")
    monkeypatch.setattr(stripe.Price, "retrieve", lambda *a, **k: base)
    monkeypatch.setattr(stripe.Price, "list", lambda *a, **k: _obj(data=[]))
    monkeypatch.setattr(stripe.Price, "create", lambda *a, **k: _obj(id="price_new"))
    out = billing.build_partner_prices(5000)
    assert out.get("_errors") in (None, [])
    assert out["pro"] == "price_new"


def test_partner_price_refuses_a_discount_that_zeroes_the_price(monkeypatch):
    """A $50 discount on a $20 plan must be reported, never sold at or below zero."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setattr(billing, "_stripe_price_id", lambda plan: f"price_{plan}_base")
    base = _obj(unit_amount=2000, currency="usd", recurring=_obj(interval="month"),
                product="prod_1")
    monkeypatch.setattr(stripe.Price, "retrieve", lambda *a, **k: base)
    out = billing.build_partner_prices(5000)
    assert out.get("starter") is None
    assert any("not smaller" in e for e in out.get("_errors", []))
