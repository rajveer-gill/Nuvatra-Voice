"""Conversational SMS session caps (billing-period scoped, atomic)."""
from datetime import datetime, timedelta, timezone

import pytest

from billing_period import billing_period_for_tenant
from conversational_sms import reserve_conversational_sms_session
from database import (
    db_conversational_sms_clear_period,
    db_conversational_sms_reserve_session,
    db_conversational_sms_session_count,
)
from plans import PLAN_CONVERSATIONAL_SMS_SESSIONS, get_plan_limits


def _tenant(client_id: str, plan: str = "starter", **extra):
    anchor = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    base = {
        "client_id": client_id,
        "plan": plan,
        "subscription_status": "active",
        "created_at": anchor.isoformat(),
        "billing_period_anchor_at": anchor.isoformat(),
        "name": "Test",
        "twilio_phone_number": "+15550001111",
    }
    base.update(extra)
    return base


def _db_available():
    try:
        import main as m

        return bool(getattr(m, "USE_DB", False))
    except ImportError:
        return False


@pytest.mark.skipif(not _db_available(), reason="PostgreSQL required")
class TestConversationalSmsSessionsDb:
    def setup_method(self):
        self.client_id = f"test-conv-{datetime.now(timezone.utc).timestamp():.0f}"
        self.tenant = _tenant(self.client_id, "starter")
        _, _, self.period_key = billing_period_for_tenant(self.tenant)
        db_conversational_sms_clear_period(self.client_id, self.period_key)

    def teardown_method(self):
        db_conversational_sms_clear_period(self.client_id, self.period_key)

    def test_under_cap_allows(self):
        cap = PLAN_CONVERSATIONAL_SMS_SESSIONS["starter"]
        for i in range(min(3, cap)):
            r = db_conversational_sms_reserve_session(
                self.client_id, self.period_key, f"+1555000{i:04d}", cap
            )
            assert r["allowed"] is True
        assert db_conversational_sms_session_count(self.client_id, self.period_key) == min(3, cap)

    def test_at_cap_denies_new_phone(self):
        cap = 2
        db_conversational_sms_clear_period(self.client_id, self.period_key)
        assert db_conversational_sms_reserve_session(
            self.client_id, self.period_key, "+15551111111", cap
        )["allowed"]
        assert db_conversational_sms_reserve_session(
            self.client_id, self.period_key, "+15552222222", cap
        )["allowed"]
        denied = db_conversational_sms_reserve_session(
            self.client_id, self.period_key, "+15553333333", cap
        )
        assert denied["allowed"] is False
        assert denied["at_cap"] is True
        assert db_conversational_sms_session_count(self.client_id, self.period_key) == 2

    def test_existing_phone_allowed_when_at_cap(self):
        cap = 1
        db_conversational_sms_clear_period(self.client_id, self.period_key)
        phone = "+15559998888"
        assert db_conversational_sms_reserve_session(self.client_id, self.period_key, phone, cap)["allowed"]
        again = db_conversational_sms_reserve_session(self.client_id, self.period_key, phone, cap)
        assert again["allowed"] is True
        assert again["is_new_session"] is False


def test_plan_limits_include_conversational_cap():
    tenant = _tenant("x", "growth")
    limits = get_plan_limits(tenant)
    assert limits["conversational_sms_sessions_cap"] == PLAN_CONVERSATIONAL_SMS_SESSIONS["growth"]


def test_billing_period_key_changes_after_anchor_month(monkeypatch):
    anchor = datetime(2024, 1, 31, tzinfo=timezone.utc)
    tenant = _tenant("period-co", created_at=anchor.isoformat(), billing_period_anchor_at=anchor.isoformat())
    _, _, key_jan = billing_period_for_tenant(tenant, datetime(2024, 2, 15, tzinfo=timezone.utc))
    _, _, key_mar = billing_period_for_tenant(tenant, datetime(2024, 3, 15, tzinfo=timezone.utc))
    assert key_jan != key_mar


def test_reserve_without_db_allows(monkeypatch):
    import main

    monkeypatch.setattr(main, "USE_DB", False)
    r = reserve_conversational_sms_session(_tenant("no-db"), "+15551234567")
    assert r.allowed is True
