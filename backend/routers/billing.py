"""Billing: subscription state + Stripe checkout/portal/webhook."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import database
import deps
import runtime
from security.webhooks import verify_stripe_event
from subscription_access import get_tenant_subscription_state

try:
    from plans import get_plan_limits
except ImportError:  # pragma: no cover
    get_plan_limits = None  # type: ignore

try:
    import stripe

    STRIPE_AVAILABLE = True
except ImportError:  # pragma: no cover
    stripe = None
    STRIPE_AVAILABLE = False

logger = logging.getLogger("nuvatra")
router = APIRouter()


@router.get("/api/subscription")
def get_subscription(tenant: Optional[dict] = Depends(deps.require_tenant)):
    """Return subscription state, plan limits, and usage for the current tenant."""
    state = get_tenant_subscription_state(tenant)
    if get_plan_limits:
        state["limits"] = get_plan_limits(tenant)
    cid = database._client_id()
    if runtime.USE_DB and cid and cid != "default":
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = database.db_usage_get(cid, month)
        state["usage"] = {
            "voice_minutes": usage.get("voice_minutes") or 0,
            "sms_count": usage.get("sms_count") or 0,
            "month": month,
        }
    else:
        state["usage"] = {
            "voice_minutes": 0,
            "sms_count": 0,
            "month": datetime.now(timezone.utc).strftime("%Y-%m"),
        }
    if deps._settings_load_debug_enabled():
        cid = (tenant or {}).get("client_id") if tenant else None
        prefix = (str(cid)[:10] + "…") if cid else "none"
        logger.info(
            "settings_load_debug GET /api/subscription client_id_prefix=%s keys=%s can_use_app=%s",
            prefix,
            sorted(state.keys()) if isinstance(state, dict) else type(state).__name__,
            (state.get("can_use_app") if isinstance(state, dict) else None),
        )
    return state


# ---------- Stripe billing ----------
def _stripe_price_id(plan: str) -> Optional[str]:
    key = f"STRIPE_{plan.upper()}_PRICE_ID"
    return (os.getenv(key) or os.getenv("STRIPE_PRICE_ID") or "").strip() or None


class CreateCheckoutSessionRequest(BaseModel):
    plan: Literal["starter", "growth", "pro"]


@router.post("/api/create-checkout-session")
def create_checkout_session(
    req: CreateCheckoutSessionRequest, tenant: Optional[dict] = Depends(deps.require_tenant)
):
    """Create a Stripe Checkout session for the given plan. Returns { url } for redirect."""
    if not STRIPE_AVAILABLE or not stripe:
        raise HTTPException(status_code=503, detail="Billing not configured")
    if not tenant or not runtime.USE_DB:
        raise HTTPException(status_code=403, detail="Tenant required")
    secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    stripe.api_key = secret
    price_id = _stripe_price_id(req.plan)
    if not price_id:
        raise HTTPException(
            status_code=503, detail=f"Price not configured for plan: {req.plan}"
        )
    frontend = (
        (os.getenv("FRONTEND_URL") or "http://localhost:3000").strip().rstrip("/")
    )
    success_url = f"{frontend}/dashboard?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend}/dashboard"
    tenant_id = tenant.get("id")
    stripe_customer_id = tenant.get("stripe_customer_id")
    if not stripe_customer_id:
        try:
            cust = stripe.Customer.create(
                metadata={
                    "tenant_id": str(tenant_id),
                    "client_id": tenant.get("client_id", ""),
                },
                email=None,
            )
            stripe_customer_id = cust.id
            database.db_tenant_update_subscription(
                tenant_id, stripe_customer_id=stripe_customer_id
            )
        except Exception as e:
            logger.error("Stripe customer create failed: %s", e)
            raise HTTPException(
                status_code=500, detail="Could not create billing customer"
            )
    try:
        session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tenant_id": str(tenant_id), "plan": req.plan},
            subscription_data={
                "metadata": {"tenant_id": str(tenant_id), "plan": req.plan}
            },
        )
        return {"url": session.url}
    except Exception as e:
        raise deps._server_error("Stripe checkout session failed", e)


@router.post("/api/create-portal-session")
def create_portal_session(tenant: Optional[dict] = Depends(deps.require_tenant)):
    """Create a Stripe Customer Portal session for managing subscription. Returns { url }."""
    if not STRIPE_AVAILABLE or not stripe:
        raise HTTPException(status_code=503, detail="Billing not configured")
    if not tenant or not runtime.USE_DB:
        raise HTTPException(status_code=403, detail="Tenant required")
    stripe_customer_id = tenant.get("stripe_customer_id")
    if not stripe_customer_id:
        # Trial users may not have a Stripe customer yet; create one so they can use the portal
        secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
        if not secret:
            raise HTTPException(status_code=503, detail="Stripe not configured")
        stripe.api_key = secret
        try:
            cust = stripe.Customer.create(
                metadata={
                    "tenant_id": str(tenant.get("id")),
                    "client_id": tenant.get("client_id", ""),
                },
                email=None,
            )
            stripe_customer_id = cust.id
            database.db_tenant_update_subscription(
                tenant.get("id"), stripe_customer_id=stripe_customer_id
            )
        except Exception as e:
            logger.error("Stripe customer create failed for portal: %s", e)
            raise HTTPException(
                status_code=500, detail="Could not create billing account"
            )
    secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    stripe.api_key = secret
    frontend = (
        (os.getenv("FRONTEND_URL") or "http://localhost:3000").strip().rstrip("/")
    )
    return_url = f"{frontend}/dashboard"
    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url,
        )
        return {"url": session.url}
    except Exception as e:
        raise deps._server_error("Stripe portal session failed", e)


@router.post("/api/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks: subscription and payment events. Raw body required for signature verification."""
    if not STRIPE_AVAILABLE or not stripe:
        raise HTTPException(status_code=503, detail="Billing not configured")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
    event, verr = verify_stripe_event(
        payload, sig, webhook_secret=secret, stripe_module=stripe
    )
    if verr:
        code = 503 if verr == "Webhook secret not configured" else 400
        raise HTTPException(status_code=code, detail=verr)
    assert event is not None
    if not runtime.USE_DB:
        return {"received": True}
    # Handle events
    if event.type == "checkout.session.completed":
        session = event.data.object
        meta = session.get("metadata") or {}
        tenant_id = meta.get("tenant_id")
        plan = meta.get("plan") or "starter"
        sub_id = session.get("subscription")
        customer_id = session.get("customer")
        if tenant_id and (sub_id or customer_id):
            database.db_tenant_update_subscription(
                tenant_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=sub_id,
                subscription_status="active",
                plan=plan,
            )
            tenant = database.db_tenant_get_by_id(tenant_id)
            deps.audit_log(
                "stripe",
                "checkout.session.completed",
                resource_type="tenant",
                resource_id=tenant_id,
                client_id=tenant["client_id"] if tenant else None,
                details={"plan": plan, "subscription_id": sub_id},
                request=request,
            )
    elif event.type == "customer.subscription.updated":
        sub = event.data.object
        sub_id = sub.get("id")
        tenant_id = (sub.get("metadata") or {}).get("tenant_id")
        status = sub.get("status")
        if tenant_id and sub_id:
            plan = (sub.get("metadata") or {}).get("plan") or "starter"
            database.db_tenant_update_subscription(
                tenant_id,
                stripe_subscription_id=sub_id,
                subscription_status=status,
                plan=plan,
            )
            tenant = database.db_tenant_get_by_id(tenant_id)
            deps.audit_log(
                "stripe",
                "customer.subscription.updated",
                resource_type="tenant",
                resource_id=tenant_id,
                client_id=tenant["client_id"] if tenant else None,
                details={"status": status, "plan": plan},
                request=request,
            )
    elif event.type == "customer.subscription.deleted":
        sub = event.data.object
        tenant_id = (sub.get("metadata") or {}).get("tenant_id")
        if tenant_id:
            tenant = database.db_tenant_get_by_id(tenant_id)
            database.db_tenant_update_subscription(tenant_id, subscription_status="canceled")
            deps.audit_log(
                "stripe",
                "customer.subscription.deleted",
                resource_type="tenant",
                resource_id=tenant_id,
                client_id=tenant["client_id"] if tenant else None,
                details={},
                request=request,
            )
    elif event.type == "invoice.payment_failed":
        inv = event.data.object
        sub_id = inv.get("subscription")
        if sub_id and runtime.USE_DB:
            tenant = database.db_tenant_get_by_stripe_subscription_id(sub_id)
            if tenant:
                database.db_tenant_update_subscription(
                    tenant["id"], subscription_status="past_due"
                )
                deps.audit_log(
                    "stripe",
                    "invoice.payment_failed",
                    resource_type="tenant",
                    resource_id=tenant["id"],
                    client_id=tenant.get("client_id"),
                    details={"subscription_id": sub_id},
                    request=request,
                )
    return {"received": True}
