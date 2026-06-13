"""Billing: subscription state + Stripe checkout/portal/webhook."""

from __future__ import annotations

import json
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
    # Self-serve signup: preferred area code for the number provisioned after checkout.
    area_code: Optional[str] = None


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
    # A tenant with no number yet is a fresh self-serve signup — give it the card-on-file
    # free trial; existing tenants upgrading from trial get charged normally.
    needs_trial = not (tenant.get("twilio_phone_number") or "").strip()
    subscription_data: dict = {"metadata": {"tenant_id": str(tenant_id), "plan": req.plan}}
    if needs_trial:
        subscription_data["trial_period_days"] = 7
    try:
        session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "tenant_id": str(tenant_id),
                "plan": req.plan,
                "area_code": (req.area_code or "").strip(),
            },
            subscription_data=subscription_data,
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


def _provision_number_for_tenant(tenant: dict, area_code: Optional[str], request: Request) -> None:
    """Self-serve: buy and wire a Twilio number (+ A2P enroll) for a tenant that has
    none yet, after checkout succeeds. Non-fatal — logged + audited on failure so the
    operator can provision manually from the admin console."""
    import twilio_provision

    acct = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    tok = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    if not (acct and tok and base):
        logger.error("self_serve_provision_skipped: missing Twilio/base config tenant=%s", tenant.get("id"))
        return
    res = twilio_provision.purchase_number(
        account_sid=acct, auth_token=tok, base_url=base, area_code=area_code
    )
    if res.get("ok") and res.get("phone_e164"):
        database.db_tenant_set_twilio_phone(tenant["id"], res["phone_e164"])
        # Store the number SID so we can release it reliably on churn without a lookup.
        if res.get("number_sid"):
            database.db_tenant_set_twilio_number_sid(tenant["id"], res["number_sid"])
        deps.audit_log(
            "system",
            "self_serve_number_provisioned",
            resource_type="tenant",
            resource_id=tenant["id"],
            client_id=tenant.get("client_id"),
            details={"phone_e164": res["phone_e164"], "a2p_enrolled": res.get("messaging_service_enrolled")},
            request=request,
        )
    else:
        logger.error("self_serve_provision_failed tenant=%s errors=%s", tenant.get("id"), res.get("errors"))
        deps.audit_log(
            "system",
            "self_serve_number_provision_failed",
            resource_type="tenant",
            resource_id=tenant["id"],
            client_id=tenant.get("client_id"),
            details={"errors": res.get("errors")},
            request=request,
        )


def _release_tenant_twilio_number(tenant: Optional[dict], request: Optional[Request] = None) -> None:
    """Release a churned tenant's Twilio number (remove from A2P service + delete) and
    clear it from the tenant row. Best-effort — never raises into a webhook handler."""
    if not tenant:
        return
    phone = (tenant.get("twilio_phone_number") or "").strip()
    if not phone:
        return  # pending tenant that never got a number — nothing to release
    import twilio_provision

    acct = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    tok = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    if not (acct and tok):
        logger.error("twilio_release_skipped: missing Twilio creds tenant=%s", tenant.get("id"))
        return
    try:
        res = twilio_provision.release_number(
            account_sid=acct,
            auth_token=tok,
            phone_e164=phone,
            number_sid=(tenant.get("twilio_number_sid") or None),
        )
        database.db_tenant_clear_twilio(tenant["id"])
        deps.audit_log(
            "system",
            "twilio_number_released",
            resource_type="tenant",
            resource_id=tenant["id"],
            client_id=tenant.get("client_id"),
            details={
                "phone_e164": phone,
                "released": res.get("released"),
                "removed_from_messaging_service": res.get("removed_from_messaging_service"),
                "errors": res.get("errors"),
            },
            request=request,
        )
    except Exception as e:
        logger.exception("twilio_release_unexpected tenant=%s: %s", tenant.get("id"), e)


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
    # Work off the verified raw payload as a plain dict — robust across Stripe SDK /
    # API-version differences (the typed event object's dict access can vary and was
    # 500ing the handler). Signature is already verified above.
    try:
        evt = json.loads(payload)
    except Exception:
        evt = {}
    etype = evt.get("type") or getattr(event, "type", "") or ""
    obj = ((evt.get("data") or {}).get("object")) or {}

    # Never 500 on a processing error — that makes Stripe retry the event forever.
    try:
        if etype == "checkout.session.completed":
            meta = obj.get("metadata") or {}
            tenant_id = meta.get("tenant_id")
            plan = meta.get("plan") or "starter"
            sub_id = obj.get("subscription")
            customer_id = obj.get("customer")
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
                # Self-serve: provision the number now that payment is set up.
                if tenant and not (tenant.get("twilio_phone_number") or "").strip():
                    _provision_number_for_tenant(
                        tenant, area_code=(meta.get("area_code") or "").strip() or None, request=request
                    )
        elif etype == "customer.subscription.updated":
            sub_id = obj.get("id")
            meta = obj.get("metadata") or {}
            tenant_id = meta.get("tenant_id")
            status = obj.get("status")
            # Customer-Portal-initiated events often carry no tenant_id metadata;
            # resolve by the stored subscription id instead (mirrors payment_failed).
            if not tenant_id and sub_id:
                t = database.db_tenant_get_by_stripe_subscription_id(sub_id)
                if t:
                    tenant_id = t.get("id")
            if tenant_id and sub_id:
                # plan is None when metadata is absent → leave the existing plan
                # untouched rather than silently downgrading a paying tenant to starter.
                plan = meta.get("plan")
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
        elif etype == "customer.subscription.deleted":
            sub_id = obj.get("id")
            tenant_id = (obj.get("metadata") or {}).get("tenant_id")
            # Portal/Stripe-initiated cancellations may lack metadata; resolve by sub id.
            if not tenant_id and sub_id:
                t = database.db_tenant_get_by_stripe_subscription_id(sub_id)
                if t:
                    tenant_id = t.get("id")
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
                # Stripe dunning is exhausted at this point — release the Twilio number
                # so we stop paying for a churned tenant. Best-effort; never 500s.
                _release_tenant_twilio_number(tenant, request=request)
        elif etype == "invoice.payment_failed":
            sub_id = obj.get("subscription")
            if sub_id:
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
    except Exception as e:
        logger.exception("stripe_webhook handler error event_type=%s: %s", etype, e)
    return {"received": True}
