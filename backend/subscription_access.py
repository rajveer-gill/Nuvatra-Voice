"""
Tenant subscription access checks (shared by dashboard deps and Twilio webhooks).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

_log = logging.getLogger("nuvatra")


def _use_database() -> bool:
    """Whether PostgreSQL tenant data is active (runtime.USE_DB after init)."""
    try:
        import runtime

        return bool(runtime.USE_DB)
    except ImportError:
        return False


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a billing timestamp that may arrive as an ISO string or a datetime."""
    if not value:
        return None
    try:
        dt = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def evaluate_billing(row: dict) -> dict[str, bool]:
    """Is this billing row currently paying for service?

    Works on a tenant or an org — both carry the same billing columns, and a franchise
    org must be judged by exactly the rules a single store is, or the two drift.

    Returns the three independent grounds for access plus their union as "active".
    """
    now = datetime.now(timezone.utc)
    status = row.get("subscription_status") or "trialing"
    exempt_dt = _parse_dt(row.get("billing_exempt_until"))
    exempt_active = bool(exempt_dt and now < exempt_dt)
    trial_active = False
    if status == "trialing":
        trial_ends_at = row.get("trial_ends_at")
        if not trial_ends_at:
            trial_active = True  # trialing with no end date = open-ended trial
        else:
            trial_dt = _parse_dt(trial_ends_at)
            # Unparseable end date: fail OPEN, matching the long-standing behaviour
            # here — never lock a trialing customer out over a bad timestamp.
            trial_active = now < trial_dt if trial_dt else True
    paid_active = status == "active"
    return {
        "exempt_active": exempt_active,
        "trial_active": trial_active,
        "paid_active": paid_active,
        "active": exempt_active or trial_active or paid_active,
    }


def _load_org_billing(org_id: Optional[str]) -> Optional[dict]:
    """Fetch an org's billing row. Imported lazily to keep this module importable
    without the DB (unit tests construct tenant dicts directly)."""
    if not org_id or not _use_database():
        return None
    try:
        import database

        return database.db_org_get_by_id(str(org_id))
    except Exception as e:
        _log.warning("org_billing_load_failed org_id=%s err=%s", org_id, type(e).__name__)
        return None


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
                "demo_mode": False,
            }
        return {
            "can_use_app": True,
            "trial_ends_at": None,
            "subscription_status": None,
            "plan": "starter",
            "billing_exempt_until": None,
            "demo_mode": False,
        }

    own = evaluate_billing(tenant)
    trial_ends_at = tenant.get("trial_ends_at")
    subscription_status = tenant.get("subscription_status") or "trialing"
    billing_exempt_until = tenant.get("billing_exempt_until")
    plan = tenant.get("plan") or "free"
    # Admin manual kill-switch overrides everything (even an active trial/subscription).
    paused = bool(tenant.get("account_paused"))
    can_use_app = own["active"] and not paused
    # Where the access came from — "org" means the group is paying for this store.
    billing_source = "own" if can_use_app else None

    # A store in an org is paid for by the org's single subscription, so it is live
    # even though it never saw a card of its own (its own subscription_status stays
    # 'incomplete' forever). Checked only when the store can't stand on its own, so a
    # store that pays for itself costs no extra query — and never when paused, because
    # the kill-switch must not be escapable by joining a group.
    org_billing = None
    if not can_use_app and not paused and tenant.get("org_id"):
        org_billing = _load_org_billing(tenant.get("org_id"))
        if org_billing and evaluate_billing(org_billing)["active"]:
            can_use_app = True
            billing_source = "org"
            plan = org_billing.get("plan") or plan
            trial_ends_at = org_billing.get("trial_ends_at")
            subscription_status = org_billing.get("subscription_status") or subscription_status

    return {
        "can_use_app": can_use_app,
        "trial_ends_at": trial_ends_at,
        "subscription_status": subscription_status,
        "plan": plan,
        "billing_exempt_until": billing_exempt_until,
        "account_paused": paused,
        # A card-free demo account exploring seeded sample data. Access here comes from
        # the exemption above; this flag only tells the UI to say so (and to let the
        # signup form through instead of bouncing it to the dashboard).
        "demo_mode": bool(tenant.get("demo_mode")),
        "org_id": tenant.get("org_id"),
        "billing_source": billing_source,
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
    # A demo account must never serve a live call, even though its exemption makes
    # can_use_app true. In practice a demo tenant has no number so no webhook can
    # reach it — this is the backstop for the one path that could break that
    # assumption (a number attached by hand from the admin console before the
    # sample services have been cleared out).
    if state.get("demo_mode"):
        return "demo_account"
    if state.get("can_use_app"):
        return None
    if state.get("account_paused"):
        return "account_paused"
    status = (state.get("subscription_status") or "").lower()
    if status == "trialing":
        return "trial_expired"
    if status == "active":
        return "subscription_inactive"
    return "subscription_required"
