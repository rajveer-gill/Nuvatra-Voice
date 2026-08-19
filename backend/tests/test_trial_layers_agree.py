"""The access gate and the feature tier must read a billing row the same way.

Two layers decide what a customer gets: subscription_access.evaluate_billing says
whether the app works at all, and plans.get_plan_limits says which features are
unlocked. They disagreed about a row with no subscription_status — evaluate_billing
read it as an open-ended trial and let the store in, plans read it as "not trialing"
and gated it to starter.

That is the state every store added to a fresh org is in, because db_org_create
inserts only the name. The store worked and its Pro features were locked: one row,
two answers, and no way to tell from the UI which was intended.
"""

from __future__ import annotations

import pytest

import plans
from subscription_access import evaluate_billing


def _row(**over):
    row = {"plan": "starter"}
    row.update(over)
    return row


@pytest.mark.parametrize(
    "row",
    [
        _row(),                                   # a fresh org: nothing set at all
        _row(subscription_status=None),
        _row(subscription_status=""),
        _row(subscription_status="trialing"),
        _row(subscription_status="trialing", trial_ends_at=None),
    ],
)
def test_an_open_ended_trial_reads_the_same_to_both_layers(row):
    assert evaluate_billing(row)["trial_active"] is True
    assert plans._is_trial_active(row) is True


def test_a_store_on_a_fresh_org_gets_the_full_experience():
    """The reported symptom: store added to a new org could use the app but had Leads
    locked behind PRO."""
    limits = plans.get_plan_limits(_row())
    assert limits["is_trial"] is True
    assert limits["has_lead_capture"] is True, "a trial is the full product, not starter"
    assert limits["has_messages"] is True


@pytest.mark.parametrize("status", ["active", "canceled", "past_due", "incomplete", "unpaid"])
def test_a_real_status_is_still_read_literally(status):
    """Only the ABSENCE of a status means trial. A cancelled customer must not be
    handed one, and a paying customer keeps their own status."""
    row = _row(subscription_status=status)
    assert plans._is_trial_active(row) is False
    assert evaluate_billing(row)["trial_active"] is False


def test_an_expired_trial_is_over_for_both():
    row = _row(subscription_status="trialing", trial_ends_at="2020-01-01T00:00:00+00:00")
    assert evaluate_billing(row)["trial_active"] is False
    assert plans._is_trial_active(row) is False
    assert plans.get_plan_limits(row)["has_lead_capture"] is False


def test_a_paying_customer_is_not_downgraded():
    row = _row(subscription_status="active", plan="pro")
    limits = plans.get_plan_limits(row)
    assert limits["is_trial"] is False
    assert limits["plan"] == "pro"
    assert limits["has_lead_capture"] is True


def test_billing_exemption_still_grants_the_full_experience():
    row = _row(subscription_status="canceled", billing_exempt_until="2099-01-01T00:00:00+00:00")
    limits = plans.get_plan_limits(row)
    assert limits["is_trial"] is False, "exempt is not a trial..."
    assert limits["has_lead_capture"] is True, "...but it is still the full product"
