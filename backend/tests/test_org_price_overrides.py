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
