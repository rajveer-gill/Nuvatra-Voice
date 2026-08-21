"""Partner pricing: a discounted price per store, not a coupon.

"$50 off each store" cannot be expressed as a Stripe coupon. amount_off comes off
the INVOICE, and a group is one subscription with quantity = store count — so a
fixed discount lands once whether that is 2 stores or 43. A percentage is per-store
but changes value with the plan: 33% is $50 off Starter, $83 off Growth, $133 off
Pro, which is the opposite of a fixed partner rate.

A discounted price is per-store by construction, because quantity multiplies the
unit price, and it holds its value when the plan changes.
"""

from __future__ import annotations

import pytest

from routers import billing


@pytest.fixture(autouse=True)
def _standard_prices(monkeypatch):
    monkeypatch.setenv("STRIPE_STARTER_PRICE_ID", "price_starter_list")
    monkeypatch.setenv("STRIPE_GROWTH_PRICE_ID", "price_growth_list")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_pro_list")
    monkeypatch.delenv("STRIPE_PRICE_ID", raising=False)


def test_a_partner_price_is_used_when_set():
    org = {"id": "o1", "price_overrides": {"starter": "price_gill_starter"}}
    assert billing._org_price_id(org, "starter") == "price_gill_starter"


def test_the_discount_survives_a_plan_change():
    """The whole reason this is a price and not a percentage: $50 off has to stay $50
    when they move from Starter to Pro."""
    org = {
        "id": "o1",
        "price_overrides": {
            "starter": "price_gill_starter",
            "growth": "price_gill_growth",
            "pro": "price_gill_pro",
        },
    }
    assert billing._org_price_id(org, "growth") == "price_gill_growth"
    assert billing._org_price_id(org, "pro") == "price_gill_pro"


def test_a_plan_without_an_override_falls_back_to_list_price():
    """A partner rate on one plan must not silently price the others at zero or fail."""
    org = {"id": "o1", "price_overrides": {"starter": "price_gill_starter"}}
    assert billing._org_price_id(org, "pro") == "price_pro_list"


@pytest.mark.parametrize("overrides", [None, {}, {"starter": ""}, {"starter": "   "}, "nonsense", []])
def test_every_other_customer_is_untouched(overrides):
    """The regression guard: an org with no override bills exactly as before."""
    assert billing._org_price_id({"id": "o1", "price_overrides": overrides}, "starter") == "price_starter_list"
    assert billing._org_price_id({}, "starter") == "price_starter_list"
    assert billing._org_price_id(None, "starter") == "price_starter_list"


@pytest.mark.parametrize("bad", ["prod_Uh3GHqPb2I8o1h", "starter", "50", "price", "PRICE_x"])
def test_a_value_that_is_not_a_price_id_is_ignored(bad, caplog):
    """A product id pasted in place of a price is the likely mistake, and it would
    reach Stripe as an opaque failure at checkout. Bill at list price instead."""
    org = {"id": "o1", "price_overrides": {"starter": bad}}
    assert billing._org_price_id(org, "starter") == "price_starter_list"


def test_the_plan_name_is_matched_case_insensitively():
    org = {"id": "o1", "price_overrides": {"starter": "price_gill_starter"}}
    assert billing._org_price_id(org, "STARTER") == "price_gill_starter"
    assert billing._org_price_id(org, " Starter ") == "price_gill_starter"


def test_no_price_configured_anywhere_returns_none(monkeypatch):
    """Checkout turns this into a 503 rather than charging something arbitrary."""
    monkeypatch.delenv("STRIPE_STARTER_PRICE_ID", raising=False)
    assert billing._org_price_id({"id": "o1"}, "starter") is None


# --- "$50 off each store" as one number ---------------------------------------
# Typing a dollar amount is the everyday path; pasting three Stripe price IDs by
# hand is three chances to paste a product where a price belongs.


class _FakeStripe:
    """Minimal Stripe stand-in that records what would be created."""

    def __init__(self, prices, existing=None):
        self.api_key = None
        self._prices = prices              # id -> price object
        self._existing = existing or {}    # product -> [price objects]
        self.created = []
        outer = self

        class Price:
            @staticmethod
            def retrieve(pid):
                return outer._prices[pid]

            @staticmethod
            def list(product=None, active=None, limit=None):
                return {"data": outer._existing.get(product, [])}

            @staticmethod
            def create(**kw):
                pid = f"price_new_{kw['unit_amount']}"
                outer.created.append(kw)
                return {"id": pid}

        self.Price = Price


def _price(pid, product, amount, currency="usd", interval="month"):
    return {"id": pid, "product": product, "unit_amount": amount,
            "currency": currency, "recurring": {"interval": interval}}


def _use(monkeypatch, fake):
    monkeypatch.setattr(billing, "stripe", fake)
    monkeypatch.setattr(billing, "STRIPE_AVAILABLE", True)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_x")


def test_a_dollar_amount_becomes_a_price_per_plan(monkeypatch):
    fake = _FakeStripe({
        "price_starter_list": _price("price_starter_list", "prod_s", 15000),
        "price_growth_list": _price("price_growth_list", "prod_g", 25000),
        "price_pro_list": _price("price_pro_list", "prod_p", 39900),
    })
    _use(monkeypatch, fake)
    out = billing.build_partner_prices(5000)
    assert set(out) == {"starter", "growth", "pro"}
    # $50 off each, not 33% off each — the amount holds across plans.
    assert [c["unit_amount"] for c in fake.created] == [10000, 20000, 34900]


def test_an_existing_matching_price_is_reused(monkeypatch):
    """A second identical price is invisible in the dashboard until you are looking
    at two of them."""
    fake = _FakeStripe(
        {"price_starter_list": _price("price_starter_list", "prod_s", 15000)},
        existing={"prod_s": [_price("price_partner_100", "prod_s", 10000)]},
    )
    monkeypatch.delenv("STRIPE_GROWTH_PRICE_ID", raising=False)
    monkeypatch.delenv("STRIPE_PRO_PRICE_ID", raising=False)
    _use(monkeypatch, fake)
    out = billing.build_partner_prices(5000)
    assert out["starter"] == "price_partner_100"
    assert fake.created == [], "should not create a duplicate"


def test_a_discount_bigger_than_the_price_is_refused(monkeypatch):
    fake = _FakeStripe({"price_starter_list": _price("price_starter_list", "prod_s", 15000)})
    monkeypatch.delenv("STRIPE_GROWTH_PRICE_ID", raising=False)
    monkeypatch.delenv("STRIPE_PRO_PRICE_ID", raising=False)
    _use(monkeypatch, fake)
    out = billing.build_partner_prices(20000)
    assert "starter" not in out
    assert any("not smaller" in e for e in out["_errors"])
    assert fake.created == [], "a negative or free price must never be created"


def test_one_plan_failing_does_not_lose_the_others(monkeypatch):
    class _Broken(_FakeStripe):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            outer = self
            good = self.Price

            class Price(good):
                @staticmethod
                def retrieve(pid):
                    if pid == "price_growth_list":
                        raise RuntimeError("stripe down")
                    return outer._prices[pid]

            self.Price = Price

    fake = _Broken({
        "price_starter_list": _price("price_starter_list", "prod_s", 15000),
        "price_pro_list": _price("price_pro_list", "prod_p", 39900),
    })
    _use(monkeypatch, fake)
    out = billing.build_partner_prices(5000)
    assert "starter" in out and "pro" in out
    assert any("growth" in e for e in out["_errors"]), "the failure must be named, not swallowed"


def test_no_stripe_key_is_reported(monkeypatch):
    monkeypatch.setattr(billing, "STRIPE_AVAILABLE", True)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    assert billing.build_partner_prices(5000)["_errors"]
