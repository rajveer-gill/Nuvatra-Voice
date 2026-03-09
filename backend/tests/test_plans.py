"""Tests for plan limits and get_plan_limits()."""
import pytest
from datetime import datetime, timezone, timedelta
from plans import get_plan_limits, PLAN_MINUTES, PLAN_STAFF_MAX, PLAN_HAS_REMINDERS, PLAN_HAS_LEAD_CAPTURE, PLAN_HAS_EXPORT, PLAN_CALL_LOG_DAYS, PLAN_SMS_AUTOMATIONS


def test_get_plan_limits_starter():
    """Starter plan (non-trial) returns correct limits."""
    tenant = {"plan": "starter", "subscription_status": "active"}
    limits = get_plan_limits(tenant)
    assert limits["plan"] == "starter"
    assert limits["minutes_cap"] == 500
    assert limits["staff_max"] == 1
    assert limits["call_log_days"] == 30
    assert limits["has_reminders"] is False
    assert limits["has_lead_capture"] is False
    assert limits["sms_automations_max"] == 0
    assert limits["has_export"] is False
    assert limits["is_trial"] is False


def test_get_plan_limits_growth():
    """Growth plan returns correct limits."""
    tenant = {"plan": "growth", "subscription_status": "active"}
    limits = get_plan_limits(tenant)
    assert limits["plan"] == "growth"
    assert limits["minutes_cap"] == 1500
    assert limits["staff_max"] == 5
    assert limits["call_log_days"] == 90
    assert limits["has_reminders"] is True
    assert limits["has_lead_capture"] is True
    assert limits["sms_automations_max"] == 2
    assert limits["has_export"] is True


def test_get_plan_limits_pro():
    """Pro plan returns correct limits."""
    tenant = {"plan": "pro", "subscription_status": "active"}
    limits = get_plan_limits(tenant)
    assert limits["plan"] == "pro"
    assert limits["minutes_cap"] == 10000
    assert limits["staff_max"] == 999
    assert limits["call_log_days"] == 9999
    assert limits["has_reminders"] is True
    assert limits["has_lead_capture"] is True
    assert limits["sms_automations_max"] == 999
    assert limits["has_export"] is True


def test_get_plan_limits_free_maps_to_starter():
    """Plan 'free' without trial maps to starter limits."""
    tenant = {"plan": "free", "subscription_status": "active"}
    limits = get_plan_limits(tenant)
    assert limits["plan"] == "starter"
    assert limits["minutes_cap"] == 500
    assert limits["staff_max"] == 1
    assert limits["has_reminders"] is False


def test_get_plan_limits_none_returns_starter():
    """None tenant returns starter limits."""
    limits = get_plan_limits(None)
    assert limits["plan"] == "starter"
    assert limits["minutes_cap"] == 500


def test_get_plan_limits_empty_plan_returns_starter():
    """Empty plan string defaults to starter."""
    tenant = {"plan": "", "subscription_status": "active"}
    limits = get_plan_limits(tenant)
    assert limits["plan"] == "starter"


def test_trial_gets_pro_limits():
    """Active trial users get full pro-level access regardless of plan."""
    future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    tenant = {"plan": "free", "subscription_status": "trialing", "trial_ends_at": future}
    limits = get_plan_limits(tenant)
    assert limits["plan"] == "starter"  # plan field shows actual plan
    assert limits["is_trial"] is True
    assert limits["minutes_cap"] == PLAN_MINUTES["pro"]
    assert limits["staff_max"] == PLAN_STAFF_MAX["pro"]
    assert limits["call_log_days"] == PLAN_CALL_LOG_DAYS["pro"]
    assert limits["has_reminders"] is True
    assert limits["has_lead_capture"] is True
    assert limits["sms_automations_max"] == PLAN_SMS_AUTOMATIONS["pro"]
    assert limits["has_export"] is True


def test_expired_trial_gets_plan_limits():
    """Expired trial falls back to the actual plan limits."""
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    tenant = {"plan": "free", "subscription_status": "trialing", "trial_ends_at": past}
    limits = get_plan_limits(tenant)
    assert limits["is_trial"] is False
    assert limits["minutes_cap"] == PLAN_MINUTES["starter"]
    assert limits["has_lead_capture"] is False
    assert limits["has_export"] is False


def test_plan_constants_have_all_plans():
    """All plan constant dicts have starter, growth, pro."""
    for name, d in [
        ("PLAN_MINUTES", PLAN_MINUTES),
        ("PLAN_STAFF_MAX", PLAN_STAFF_MAX),
        ("PLAN_HAS_REMINDERS", PLAN_HAS_REMINDERS),
        ("PLAN_HAS_LEAD_CAPTURE", PLAN_HAS_LEAD_CAPTURE),
        ("PLAN_HAS_EXPORT", PLAN_HAS_EXPORT),
        ("PLAN_CALL_LOG_DAYS", PLAN_CALL_LOG_DAYS),
        ("PLAN_SMS_AUTOMATIONS", PLAN_SMS_AUTOMATIONS),
    ]:
        assert set(d.keys()) == {"starter", "growth", "pro"}, f"{name} missing keys"
