"""
Tenant subscription access checks (shared by dashboard deps and Twilio webhooks).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

_log = logging.getLogger("nuvatra")


def _use_database() -> bool:
    """Whether PostgreSQL tenant data is active (main.USE_DB after init)."""
    try:
        import main as m

        return bool(getattr(m, "USE_DB", False))
    except ImportError:
        return False


def get_tenant_subscription_state(tenant: Optional[dict]) -> dict[str, Any]:
    """
    Return subscription state for the tenant.

    When tenant is None and DB is off, can_use_app is True (legacy single-tenant dev).
    When tenant is None and DB is on, can_use_app is False (unknown destination).
    When tenant is present, subscription fields are always evaluated.
    """
    if not tenant:
        if _use_database():
            return {
                "can_use_app": False,
                "trial_ends_at": None,
                "subscription_status": None,
                "plan": "starter",
                "billing_exempt_until": None,
            }
        return {
            "can_use_app": True,
            "trial_ends_at": None,
            "subscription_status": None,
            "plan": "starter",
            "billing_exempt_until": None,
        }

    now = datetime.now(timezone.utc)
    trial_ends_at = tenant.get("trial_ends_at")
    subscription_status = tenant.get("subscription_status") or "trialing"
    billing_exempt_until = tenant.get("billing_exempt_until")
    plan = tenant.get("plan") or "free"
    exempt_active = False
    if billing_exempt_until:
        try:
            exempt_dt = (
                datetime.fromisoformat(billing_exempt_until.replace("Z", "+00:00"))
                if isinstance(billing_exempt_until, str)
                else billing_exempt_until
            )
            if exempt_dt.tzinfo is None:
                exempt_dt = exempt_dt.replace(tzinfo=timezone.utc)
            exempt_active = now < exempt_dt
        except Exception:
            pass
    trial_active = False
    if subscription_status == "trialing":
        if not trial_ends_at:
            trial_active = True
        else:
            try:
                trial_dt = (
                    datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
                    if isinstance(trial_ends_at, str)
                    else trial_ends_at
                )
                if trial_dt.tzinfo is None:
                    trial_dt = trial_dt.replace(tzinfo=timezone.utc)
                trial_active = now < trial_dt
            except Exception:
                trial_active = True
    paid_active = subscription_status == "active"
    can_use_app = exempt_active or trial_active or paid_active
    return {
        "can_use_app": can_use_app,
        "trial_ends_at": trial_ends_at,
        "subscription_status": subscription_status,
        "plan": plan,
        "billing_exempt_until": billing_exempt_until,
    }


def tenant_can_use_app(tenant: Optional[dict]) -> bool:
    """True when tenant may use the product (trial, paid, or billing exempt)."""
    return bool(get_tenant_subscription_state(tenant).get("can_use_app"))


def webhook_access_denial_reason(tenant: Optional[dict]) -> Optional[str]:
    """
    When webhooks must reject service, return a short reason code for logs; else None.

    Missing tenant in DB mode is treated as denial (unknown destination).
    """
    if _use_database() and not tenant:
        return "tenant_not_found"
    if tenant is None:
        return None
    state = get_tenant_subscription_state(tenant)
    if state.get("can_use_app"):
        return None
    status = (state.get("subscription_status") or "").lower()
    if status == "trialing":
        return "trial_expired"
    if status == "active":
        return "subscription_inactive"
    return "subscription_required"
