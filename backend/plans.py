"""
Plan limits and helpers for Starter/Growth/Pro tiers.
"""
from typing import Optional

PLAN_MINUTES = {"starter": 500, "growth": 1500, "pro": 3500}
# Staff roster (booking/calendar): effectively unlimited; abuse capped in staff_transfers.STAFF_ROSTER_MAX.
STAFF_ROSTER_UNLIMITED = 500
# Live call transfer destinations (Twilio Dial) — plan-gated.
PLAN_TRANSFER_MAX = {"starter": 1, "growth": 5, "pro": 999}
PLAN_CALL_LOG_DAYS = {"starter": 30, "growth": 90, "pro": 9999}
PLAN_HAS_REMINDERS = {"starter": False, "growth": True, "pro": True}
PLAN_HAS_LEAD_CAPTURE = {"starter": False, "growth": True, "pro": True}
PLAN_SMS_AUTOMATIONS = {"starter": 0, "growth": 2, "pro": 999}
PLAN_HAS_EXPORT = {"starter": False, "growth": True, "pro": True}
# SMS conversations inbox (read/search full caller<->receptionist threads). Texting
# itself happens on all plans; the inbox viewer is a Growth+ management perk.
PLAN_HAS_MESSAGES = {"starter": False, "growth": True, "pro": True}
PLAN_HAS_CALL_RECORDING = {"starter": False, "growth": True, "pro": True}
PLAN_CONVERSATIONAL_SMS_SESSIONS = {"starter": 100, "growth": 300, "pro": 1000}
# Plan list prices (USD/month) — the basis for referral commissions. Keep in sync
# with the prices shown on the create-business page and your Stripe products.
PLAN_LIST_PRICE_USD = {"starter": 150, "growth": 250, "pro": 399}

# Validate all dicts have expected keys at import
_EXPECTED_PLANS = {"starter", "growth", "pro"}
for name, d in [
    ("PLAN_MINUTES", PLAN_MINUTES),
    ("PLAN_TRANSFER_MAX", PLAN_TRANSFER_MAX),
    ("PLAN_CALL_LOG_DAYS", PLAN_CALL_LOG_DAYS),
    ("PLAN_HAS_REMINDERS", PLAN_HAS_REMINDERS),
    ("PLAN_HAS_LEAD_CAPTURE", PLAN_HAS_LEAD_CAPTURE),
    ("PLAN_SMS_AUTOMATIONS", PLAN_SMS_AUTOMATIONS),
    ("PLAN_HAS_EXPORT", PLAN_HAS_EXPORT),
    ("PLAN_HAS_MESSAGES", PLAN_HAS_MESSAGES),
    ("PLAN_HAS_CALL_RECORDING", PLAN_HAS_CALL_RECORDING),
    ("PLAN_CONVERSATIONAL_SMS_SESSIONS", PLAN_CONVERSATIONAL_SMS_SESSIONS),
    ("PLAN_LIST_PRICE_USD", PLAN_LIST_PRICE_USD),
]:
    if set(d.keys()) != _EXPECTED_PLANS:
        raise ValueError(f"{name} missing keys: expected {_EXPECTED_PLANS}, got {set(d.keys())}")

# --- Referral program economics (all money in integer cents to avoid float drift) ---
REFERRAL_SIGNUP_BOUNTY_CENTS = 20000   # $200 once the referred client's first paid charge clears
REFERRAL_MRR_RATE = 0.25               # 25% of plan list price per paid month
REFERRAL_MRR_MONTHS_CAP = 12           # for up to 12 paid months after the first paid charge
REFERRAL_FREE_MONTH_DAYS = 30          # free first month granted to a referred signup


def referral_mrr_commission_cents(plan: Optional[str]) -> int:
    """Monthly referral commission (cents) = 25% of the plan's list price."""
    price = PLAN_LIST_PRICE_USD.get(_normalize_plan(plan), 0)
    return round(price * 100 * REFERRAL_MRR_RATE)


def _normalize_plan(raw: Optional[str]) -> str:
    """Normalize plan string. 'free' -> 'starter' for limits."""
    p = (raw or "starter").lower().strip()
    return "starter" if p == "free" else p


def _is_trial_active(tenant: Optional[dict]) -> bool:
    """Check if the tenant has an active trial."""
    if not tenant:
        return False
    # A missing status means "trialing", matching subscription_access.evaluate_billing,
    # which is the shared gate deciding whether the app works at all. They disagreed:
    # a fresh org is created with no status, so evaluate_billing granted an open-ended
    # trial and let the store in, while this read the same row as "not trialing" and
    # gated it to starter. A store you can use but whose Pro features are locked is one
    # row giving two answers, and the access layer's reading is the documented one.
    status = (tenant.get("subscription_status") or "trialing").lower()
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


def _is_billing_exempt_active(tenant: Optional[dict]) -> bool:
    """Check if the tenant has an active admin billing exemption (a comped free window)."""
    if not tenant:
        return False
    exempt_until = tenant.get("billing_exempt_until")
    if not exempt_until:
        return False
    try:
        from datetime import datetime, timezone
        exempt_dt = (
            datetime.fromisoformat(exempt_until.replace("Z", "+00:00"))
            if isinstance(exempt_until, str)
            else exempt_until
        )
        if exempt_dt.tzinfo is None:
            exempt_dt = exempt_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < exempt_dt
    except Exception:
        return False


def _billing_row_for_limits(tenant: Optional[dict]) -> Optional[dict]:
    """The row that decides this tenant's feature tier.

    Normally the tenant itself. But a store inside an org never has its own
    subscription — the group pays once and the store's subscription_status stays
    'incomplete' forever — so its trial and plan live on the org. Without this, an
    org store on a 7-day trial reads as "no trial" and gets gated down to its paid
    tier, which is exactly backwards: the trial is meant to grant full Pro access.

    Only consulted when the tenant can't stand on its own, so a store that pays for
    itself costs no extra query. Mirrors subscription_access._load_org_billing.
    """
    if not tenant:
        return None
    own_status = (tenant.get("subscription_status") or "").lower()
    if _is_trial_active(tenant) or _is_billing_exempt_active(tenant) or own_status == "active":
        return tenant
    org_id = tenant.get("org_id")
    if not org_id:
        return tenant
    try:
        import runtime

        if not runtime.USE_DB:
            return tenant
        import database

        return database.db_org_get_by_id(str(org_id)) or tenant
    except Exception:
        return tenant


def get_plan_limits(tenant: Optional[dict]) -> dict:
    """Return plan limits dict. Any free-access grant gets the FULL (pro-tier) experience.

    Both an active trial (subscription_status="trialing") and an active admin billing
    exemption (billing_exempt_until in the future) map to pro-tier features — so a comped
    or extended tenant is never gated to starter. (Billing exemption is checked here rather
    than forcing status="trialing", so a comped *paying* customer keeps their "active" status.)
    """
    # For a store in an org this is the org's billing row, since that's where the
    # trial and subscription actually live (see _billing_row_for_limits).
    billing = _billing_row_for_limits(tenant)
    plan = _normalize_plan(
        (tenant.get("plan") if tenant else None) or (billing.get("plan") if billing else None)
    )
    full_access = _is_trial_active(billing) or _is_billing_exempt_active(billing)
    effective = "pro" if full_access else plan
    return {
        "plan": plan,
        "minutes_cap": PLAN_MINUTES.get(effective, 500),
        "staff_max": STAFF_ROSTER_UNLIMITED,
        "transfer_max": PLAN_TRANSFER_MAX.get(effective, 1),
        "call_log_days": PLAN_CALL_LOG_DAYS.get(effective, 30),
        "has_reminders": PLAN_HAS_REMINDERS.get(effective, False),
        "has_lead_capture": PLAN_HAS_LEAD_CAPTURE.get(effective, False),
        "sms_automations_max": PLAN_SMS_AUTOMATIONS.get(effective, 0),
        "has_export": PLAN_HAS_EXPORT.get(effective, False),
        "has_messages": PLAN_HAS_MESSAGES.get(effective, False),
        "has_call_recording": PLAN_HAS_CALL_RECORDING.get(effective, False),
        "conversational_sms_sessions_cap": PLAN_CONVERSATIONAL_SMS_SESSIONS.get(effective, 100),
        # SMS cap reuses the conversational-SMS-session quota (same metered unit as
        # tenant_usage.sms_count); exposed under a dedicated key for usage gating/billing.
        "sms_cap": PLAN_CONVERSATIONAL_SMS_SESSIONS.get(effective, 100),
        "is_trial": _is_trial_active(billing),
    }
