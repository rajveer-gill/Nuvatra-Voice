"""Monthly overage billing cron: confirms Stripe is charged the right amounts
for voice and SMS overage, per-channel, idempotently."""

from unittest.mock import MagicMock

import database
import runtime
from routers import cron


def _setup(monkeypatch, *, usage, caps, processed=False, status="active", customer="cus_1"):
    monkeypatch.setattr(cron, "_verify_cron_secret", lambda request: True)
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(cron, "STRIPE_AVAILABLE", True)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(cron, "get_plan_limits", lambda t: caps)
    monkeypatch.setattr(database, "db_cron_run_start", lambda name: 1)
    monkeypatch.setattr(database, "db_cron_run_finish", lambda *a, **k: None)
    monkeypatch.setattr(
        database, "db_tenant_list_all",
        lambda: [{"client_id": "salon", "subscription_status": status, "stripe_customer_id": customer}],
    )
    monkeypatch.setattr(database, "db_overage_processed_exists", lambda cid, m: processed)
    inserted = []
    monkeypatch.setattr(database, "db_overage_processed_insert", lambda cid, m: inserted.append((cid, m)))
    monkeypatch.setattr(database, "db_usage_get", lambda cid, m: usage)
    items = []
    fake_stripe = MagicMock()
    fake_stripe.InvoiceItem.create.side_effect = lambda **kw: items.append(kw)
    monkeypatch.setattr(cron, "stripe", fake_stripe)
    return items, inserted


def test_bills_voice_and_sms_overage(monkeypatch):
    # 600 min used vs 500 cap = 100 over @ $0.15 = $15.00 = 1500c
    # 120 texts vs 100 cap = 20 over @ $0.05 = $1.00 = 100c
    items, inserted = _setup(
        monkeypatch,
        usage={"voice_minutes": 600, "sms_count": 120},
        caps={"minutes_cap": 500, "sms_cap": 100},
    )
    res = cron.cron_process_overage(MagicMock())
    assert res["invoices_created"] == 2
    amounts = sorted(i["amount"] for i in items)
    assert amounts == [100, 1500]
    assert all(i["currency"] == "usd" and i["customer"] == "cus_1" for i in items)
    descriptions = " ".join(i["description"] for i in items)
    assert "minutes" in descriptions and "texts" in descriptions
    assert inserted == [("salon", inserted[0][1])]  # processed marker written


def test_bills_only_the_channel_that_is_over(monkeypatch):
    # voice under cap, sms over
    items, _ = _setup(
        monkeypatch,
        usage={"voice_minutes": 400, "sms_count": 130},
        caps={"minutes_cap": 500, "sms_cap": 100},
    )
    res = cron.cron_process_overage(MagicMock())
    assert res["invoices_created"] == 1
    assert items[0]["amount"] == 150  # 30 texts * $0.05
    assert "texts" in items[0]["description"]


def test_no_charge_when_within_caps(monkeypatch):
    items, inserted = _setup(
        monkeypatch,
        usage={"voice_minutes": 100, "sms_count": 10},
        caps={"minutes_cap": 500, "sms_cap": 100},
    )
    res = cron.cron_process_overage(MagicMock())
    assert res["invoices_created"] == 0
    assert items == []
    assert len(inserted) == 1  # still marks processed so we don't recheck


def test_idempotent_skip_when_already_processed(monkeypatch):
    items, _ = _setup(
        monkeypatch,
        usage={"voice_minutes": 999, "sms_count": 999},
        caps={"minutes_cap": 500, "sms_cap": 100},
        processed=True,
    )
    res = cron.cron_process_overage(MagicMock())
    assert res["invoices_created"] == 0
    assert items == []


def test_skips_non_active_subscriptions(monkeypatch):
    items, _ = _setup(
        monkeypatch,
        usage={"voice_minutes": 999, "sms_count": 999},
        caps={"minutes_cap": 500, "sms_cap": 100},
        status="trialing",
    )
    res = cron.cron_process_overage(MagicMock())
    assert res["invoices_created"] == 0
    assert items == []
