"""Referral program webhook tests (mocked Stripe, no live calls)."""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def _post(client, billing, event_dict, configure=None):
    with patch.object(billing, "stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = MagicMock()  # signature OK
        if configure:
            configure(mock_stripe)
        resp = client.post(
            "/api/stripe-webhook",
            content=json.dumps(event_dict).encode(),
            headers={"Content-Type": "application/json", "stripe-signature": "v0,fake"},
        )
        return resp, mock_stripe


def _checkout_event(referral_code="JANE"):
    return {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_1", "customer": "cus_1", "subscription": "sub_1",
            "customer_details": {"email": "owner@example.com"},
            "metadata": {"tenant_id": "t-1", "plan": "growth", "referral_code": referral_code},
        }},
    }


def _stripe_with_card(fingerprint="fp_abc", created=1_700_000_000):
    """Configure the mock so Subscription.retrieve yields a real created + fingerprint."""
    def configure(mock_stripe):
        card = SimpleNamespace(fingerprint=fingerprint)
        pm = SimpleNamespace(card=card)
        mock_stripe.Subscription.retrieve.return_value = SimpleNamespace(
            created=created, default_payment_method=pm
        )
        mock_stripe.Subscription.modify = MagicMock()
    return configure


def _common_checkout_mocks(monkeypatch, *, fingerprint_seen=False, email_seen=False):
    import database, deps, runtime
    monkeypatch.setattr(runtime, "USE_DB", True)
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    monkeypatch.setattr(database, "db_tenant_update_subscription", lambda *a, **k: True)
    # Tenant already has a number → provisioning skipped.
    monkeypatch.setattr(database, "db_tenant_get_by_id",
                        lambda tid: {"id": tid, "client_id": "c-1", "twilio_phone_number": "+15551112222", "plan": "growth"})
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(database, "db_signup_payment_method_record", lambda *a, **k: True)
    monkeypatch.setattr(database, "db_referral_code_get_by_code", lambda code, active_only=True: {"id": 1, "referrer_name": "Jane Doe"})
    monkeypatch.setattr(database, "db_referral_redemption_create", lambda *a, **k: 10)
    updates = []
    monkeypatch.setattr(database, "db_referral_redemption_update", lambda rid, **kw: updates.append(kw) or True)
    monkeypatch.setattr(database, "db_signup_fingerprint_seen", lambda fp, exclude_tenant_id=None: fingerprint_seen)
    monkeypatch.setattr(database, "db_signup_email_seen", lambda em, exclude_tenant_id=None: email_seen)
    return updates


def test_valid_code_grants_free_month(client, monkeypatch):
    import database  # noqa
    from routers import billing
    updates = _common_checkout_mocks(monkeypatch)
    try:
        resp, mock_stripe = _post(client, billing, _checkout_event(), _stripe_with_card())
        assert resp.status_code == 200
        # Stripe trial extended ~30 days → free month granted.
        assert mock_stripe.Subscription.modify.called
        kwargs = mock_stripe.Subscription.modify.call_args.kwargs
        assert "trial_end" in kwargs
        assert any(u.get("status") == "granted" for u in updates)
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)


def test_duplicate_card_flags_and_keeps_trial(client, monkeypatch):
    from routers import billing
    updates = _common_checkout_mocks(monkeypatch, fingerprint_seen=True)
    try:
        resp, mock_stripe = _post(client, billing, _checkout_event(), _stripe_with_card())
        assert resp.status_code == 200
        assert not mock_stripe.Subscription.modify.called  # no free month
        flagged = [u for u in updates if u.get("status") == "flagged"]
        assert flagged and flagged[0]["flagged_reason"] == "duplicate_card"
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)


def test_duplicate_email_flags(client, monkeypatch):
    from routers import billing
    updates = _common_checkout_mocks(monkeypatch, email_seen=True)
    try:
        resp, mock_stripe = _post(client, billing, _checkout_event(), _stripe_with_card())
        assert resp.status_code == 200
        assert not mock_stripe.Subscription.modify.called
        assert any(u.get("flagged_reason") == "duplicate_email" for u in updates)
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)


def test_invalid_code_no_redemption(client, monkeypatch):
    import database
    from routers import billing
    _common_checkout_mocks(monkeypatch)
    created = []
    monkeypatch.setattr(database, "db_referral_code_get_by_code", lambda code, active_only=True: None)
    monkeypatch.setattr(database, "db_referral_redemption_create", lambda *a, **k: created.append(1) or 99)
    try:
        resp, mock_stripe = _post(client, billing, _checkout_event("BADCODE"), _stripe_with_card())
        assert resp.status_code == 200
        assert created == []  # no redemption row for an unknown code
        assert not mock_stripe.Subscription.modify.called
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)


# --- invoice.payment_succeeded ---

def _invoice_event(amount_paid=25000, invoice_id="in_1"):
    return {
        "type": "invoice.payment_succeeded",
        "data": {"object": {"id": invoice_id, "subscription": "sub_1", "amount_paid": amount_paid}},
    }


def _commission_mocks(monkeypatch, redemption, *, mrr_count=0):
    import database, deps, runtime
    monkeypatch.setattr(runtime, "USE_DB", True)
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(database, "db_referral_redemption_get_by_subscription", lambda sub: redemption)
    monkeypatch.setattr(database, "db_tenant_get_by_id", lambda tid: {"id": tid, "plan": "growth"})
    monkeypatch.setattr(database, "db_referral_redemption_update", lambda rid, **kw: True)
    monkeypatch.setattr(database, "db_referral_commission_count_mrr", lambda rid: mrr_count)
    inserts = []
    monkeypatch.setattr(database, "db_referral_commission_insert",
                        lambda rid, kind, period, amount, plan, code, ref: inserts.append((kind, period, amount)) or len(inserts))
    return inserts


def test_first_paid_invoice_creates_bounty_and_mrr(client, monkeypatch):
    from routers import billing
    red = {"id": 10, "tenant_id": "t-1", "status": "granted", "first_paid_at": None,
           "plan_at_signup": "growth", "code_snapshot": "JANE", "referrer_name_snapshot": "Jane Doe"}
    inserts = _commission_mocks(monkeypatch, red)
    try:
        resp, _ = _post(client, billing, _invoice_event())
        assert resp.status_code == 200
        kinds = [i[0] for i in inserts]
        assert "signup_bounty" in kinds  # $200 bounty
        assert "mrr" in kinds            # first 25% commission
        bounty = next(i for i in inserts if i[0] == "signup_bounty")
        assert bounty[2] == 20000        # $200 in cents
        mrr = next(i for i in inserts if i[0] == "mrr")
        assert mrr[2] == 6250            # 25% of $250 growth
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)


def test_zero_dollar_trial_invoice_skipped(client, monkeypatch):
    import database
    from routers import billing
    called = []
    import runtime
    monkeypatch.setattr(runtime, "USE_DB", True)
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    monkeypatch.setattr(database, "db_referral_redemption_get_by_subscription", lambda sub: called.append(1) or None)
    try:
        resp, _ = _post(client, billing, _invoice_event(amount_paid=0))
        assert resp.status_code == 200
        assert called == []  # $0 invoice → never looks up a redemption
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)


def test_flagged_redemption_earns_nothing(client, monkeypatch):
    from routers import billing
    red = {"id": 10, "tenant_id": "t-1", "status": "flagged", "first_paid_at": None,
           "plan_at_signup": "growth", "code_snapshot": "JANE", "referrer_name_snapshot": "Jane Doe"}
    inserts = _commission_mocks(monkeypatch, red)
    try:
        resp, _ = _post(client, billing, _invoice_event())
        assert resp.status_code == 200
        assert inserts == []  # flagged → no payout ever
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)


def test_mrr_capped_at_12(client, monkeypatch):
    from routers import billing
    # Already converted (bounty paid) and 12 MRR entries already exist → no new mrr.
    red = {"id": 10, "tenant_id": "t-1", "status": "converted", "first_paid_at": "2026-01-01T00:00:00+00:00",
           "plan_at_signup": "growth", "code_snapshot": "JANE", "referrer_name_snapshot": "Jane Doe"}
    inserts = _commission_mocks(monkeypatch, red, mrr_count=12)
    try:
        resp, _ = _post(client, billing, _invoice_event(invoice_id="in_13"))
        assert resp.status_code == 200
        assert inserts == []  # cap reached
    finally:
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
