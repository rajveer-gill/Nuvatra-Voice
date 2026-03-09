"""
Plan limits and helpers for Starter/Growth/Pro tiers.
"""
from typing import Optional

PLAN_MINUTES = {"starter": 500, "growth": 1500, "pro": 10000}
PLAN_STAFF_MAX = {"starter": 1, "growth": 5, "pro": 999}
PLAN_CALL_LOG_DAYS = {"starter": 30, "growth": 90, "pro": 9999}
PLAN_HAS_REMINDERS = {"starter": False, "growth": True, "pro": True}
PLAN_HAS_LEAD_CAPTURE = {"starter": False, "growth": True, "pro": True}
PLAN_SMS_AUTOMATIONS = {"starter": 0, "growth": 2, "pro": 999}
PLAN_HAS_EXPORT = {"starter": False, "growth": True, "pro": True}

# Validate all dicts have expected keys at import
_EXPECTED_PLANS = {"starter", "growth", "pro"}
for name, d in [
    ("PLAN_MINUTES", PLAN_MINUTES),
    ("PLAN_STAFF_MAX", PLAN_STAFF_MAX),
    ("PLAN_CALL_LOG_DAYS", PLAN_CALL_LOG_DAYS),
    ("PLAN_HAS_REMINDERS", PLAN_HAS_REMINDERS),
    ("PLAN_HAS_LEAD_CAPTURE", PLAN_HAS_LEAD_CAPTURE),
    ("PLAN_SMS_AUTOMATIONS", PLAN_SMS_AUTOMATIONS),
    ("PLAN_HAS_EXPORT", PLAN_HAS_EXPORT),
]:
    if set(d.keys()) != _EXPECTED_PLANS:
        raise ValueError(f"{name} missing keys: expected {_EXPECTED_PLANS}, got {set(d.keys())}")


def _normalize_plan(raw: Optional[str]) -> str:
    """Normalize plan string. 'free' -> 'starter' for limits."""
    p = (raw or "starter").lower().strip()
    return "starter" if p == "free" else p


def _is_trial_active(tenant: Optional[dict]) -> bool:
    """Check if the tenant has an active trial."""
    if not tenant:
        return False
    status = (tenant.get("subscription_status") or "").lower()
    if status != "trialing":
        return False
    trial_ends_at = tenant.get("trial_ends_at")
    if not trial_ends_at:
        return True
    try:
        from datetime import datetime, timezone
        trial_dt = datetime.fromisoformat(
            trial_ends_at.replace("Z", "+00:00")
        ) if isinstance(trial_ends_at, str) else trial_ends_at
        if trial_dt.tzinfo is None:
            trial_dt = trial_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < trial_dt
    except Exception:
        return False


def get_plan_limits(tenant: Optional[dict]) -> dict:
    """Return plan limits dict. Trial users get full pro-level access."""
    plan = _normalize_plan(tenant.get("plan") if tenant else None)
    effective = "pro" if _is_trial_active(tenant) else plan
    return {
        "plan": plan,
        "minutes_cap": PLAN_MINUTES.get(effective, 500),
        "staff_max": PLAN_STAFF_MAX.get(effective, 1),
        "call_log_days": PLAN_CALL_LOG_DAYS.get(effective, 30),
        "has_reminders": PLAN_HAS_REMINDERS.get(effective, False),
        "has_lead_capture": PLAN_HAS_LEAD_CAPTURE.get(effective, False),
        "sms_automations_max": PLAN_SMS_AUTOMATIONS.get(effective, 0),
        "has_export": PLAN_HAS_EXPORT.get(effective, False),
        "is_trial": _is_trial_active(tenant),
    }
