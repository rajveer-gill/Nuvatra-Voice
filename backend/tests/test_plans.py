"""Tests for plan limits and get_plan_limits()."""
import pytest
from plans import get_plan_limits, PLAN_MINUTES, PLAN_STAFF_MAX, PLAN_HAS_REMINDERS, PLAN_HAS_LEAD_CAPTURE, PLAN_HAS_EXPORT, PLAN_CALL_LOG_DAYS, PLAN_SMS_AUTOMATIONS


def test_get_plan_limits_starter():
    """Starter plan returns correct limits."""
    tenant = {"plan": "starter"}
    limits = get_plan_limits(tenant)
    assert limits["plan"] == "starter"
    assert limits["minutes_cap"] == 500
    assert limits["staff_max"] == 1
    assert limits["call_log_days"] == 30
    assert limits["has_reminders"] is False
    assert limits["has_lead_capture"] is False
    assert limits["sms_automations_max"] == 0
    assert limits["has_export"] is False


def test_get_plan_limits_growth():
    """Growth plan returns correct limits."""
    tenant = {"plan": "growth"}
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
    tenant = {"plan": "pro"}
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
    """Plan 'free' maps to starter limits."""
    tenant = {"plan": "free"}
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
    tenant = {"plan": ""}
    limits = get_plan_limits(tenant)
    assert limits["plan"] == "starter"


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
