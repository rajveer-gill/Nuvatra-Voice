"""Billing: subscription state + Stripe checkout/portal/webhook."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
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
    # Use the tenant's client_id directly — a contextvar set inside the sync
    # require_tenant dependency does not survive into this sync endpoint, so
    # database._client_id() would fall back to "default" and show zero usage.
    cid = ((tenant or {}).get("client_id") or "").strip() or database._client_id()
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


def _subscription_status_and_trial(sub_id: Optional[str]):
    """Read a Stripe subscription's real status + trial end so the tenant mirrors it.

    A self-serve signup starts a 7-day trial, so Stripe reports status 'trialing'
    with a trial_end. Recording that (instead of a hardcoded 'active') is what makes
    _is_trial_active true and unlocks full Pro-tier features during the trial.
    Falls back to ('active', None) if the subscription can't be read.
    """
    if not sub_id or not (STRIPE_AVAILABLE and stripe):
        return "active", None
    try:
        stripe.api_key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
        sub = stripe.Subscription.retrieve(sub_id)
        status = getattr(sub, "status", None)
        if not isinstance(status, str) or not status:
            status = "active"
        trial_ends_at = None
        t_end = getattr(sub, "trial_end", None)
        if isinstance(t_end, (int, float)):
            from datetime import datetime, timezone

            trial_ends_at = datetime.fromtimestamp(int(t_end), tz=timezone.utc)
        return status, trial_ends_at
    except Exception as e:
        logger.warning("stripe_subscription_retrieve_failed sub=%s err=%s", sub_id, type(e).__name__)
        return "active", None


def _plan_from_price_id(price_id: Optional[str]) -> Optional[str]:
    """Reverse-map a Stripe price ID to a plan name. Used for Customer-Portal plan
    switches, where the new plan is carried in the subscription's line items (not our
    metadata). Returns None for an unrecognized price so we never guess."""
    pid = (price_id or "").strip()
    if not pid:
        return None
    for plan in ("starter", "growth", "pro"):
        if (os.getenv(f"STRIPE_{plan.upper()}_PRICE_ID") or "").strip() == pid:
            return plan
    return None


def _subscription_plan_from_obj(obj: dict) -> Optional[str]:
    """Derive the plan from a Stripe subscription object's first line-item price."""
    try:
        items = ((obj.get("items") or {}).get("data")) or []
        if items:
            return _plan_from_price_id((items[0].get("price") or {}).get("id"))
    except Exception:
        pass
    return None


class CreateCheckoutSessionRequest(BaseModel):
    plan: Literal["starter", "growth", "pro"]
    # Self-serve signup: preferred area code for the number provisioned after checkout.
    area_code: Optional[str] = None
    # Optional referral code; validated server-side in the webhook (free month is granted
    # only after the card/email anti-abuse check passes).
    referral_code: Optional[str] = None


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
    ref_code = (req.referral_code or "").strip().upper()
    subscription_data: dict = {
        "metadata": {"tenant_id": str(tenant_id), "plan": req.plan, "referral_code": ref_code}
    }
    if needs_trial:
        # Normal 7-day trial here; a valid referral extends it to a free month in the
        # webhook, AFTER the card/email anti-abuse check.
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
                "referral_code": ref_code,
            },
            subscription_data=subscription_data,
        )
        return {"url": session.url}
    except Exception as e:
        raise deps._server_error("Stripe checkout session failed", e)


@router.get("/api/referral/validate")
def validate_referral_code(code: str, _user_id: str = Depends(deps.require_user)):
    """Signed-in check so the signup page can confirm a code before checkout. Uses
    require_user (NOT require_tenant) because the user has no tenant yet mid-signup.
    Returns the MINIMUM (valid + referrer first name) — never contact or payout terms."""
    if not runtime.USE_DB:
        return {"valid": False}
    rc = database.db_referral_code_get_by_code(code, active_only=True)
    if not rc:
        return {"valid": False}
    first_name = (rc.get("referrer_name") or "").strip().split(" ")[0]
    return {"valid": True, "referrer_first_name": first_name}


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
        # A paying customer with no phone line is urgent — alert so it can be fixed manually.
        try:
            import alerts

            alerts.notify_failure(
                "provision", "number_purchase_failed", tenant.get("id"),
                f"Self-serve number provisioning failed for {tenant.get('client_id')}",
                payload={"errors": res.get("errors")},
            )
        except Exception:
            pass


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


def _referral_card_fingerprint_and_email(session_obj: dict, sub_id, customer_id):
    """Best-effort: return (card_fingerprint, email, subscription_obj). Null-safe."""
    fp = None
    email = None
    sub_obj = None
    try:
        cd = session_obj.get("customer_details") or {}
        email = (cd.get("email") or "").strip() or None
    except Exception:
        pass
    try:
        if sub_id:
            sub_obj = stripe.Subscription.retrieve(sub_id, expand=["default_payment_method"])
            pm = getattr(sub_obj, "default_payment_method", None)
            card = getattr(pm, "card", None) if pm else None
            fp = getattr(card, "fingerprint", None) if card else None
        if not fp and customer_id:
            pms = stripe.PaymentMethod.list(customer=customer_id, type="card")
            data = getattr(pms, "data", None) or []
            if data:
                card = getattr(data[0], "card", None)
                fp = getattr(card, "fingerprint", None) if card else None
        if not email and customer_id:
            cust = stripe.Customer.retrieve(customer_id)
            email = (getattr(cust, "email", None) or "").strip() or None
    except Exception as e:
        logger.warning("referral_fingerprint_lookup_failed sub=%s: %s", sub_id, e)
    return fp, email, sub_obj


def _process_referral_on_checkout(session_obj, meta, tenant_id, sub_id, customer_id, plan, request):
    """Record the signup's card/email (global anti-abuse ledger) and, if a valid referral
    code was used, grant the free month or flag the redemption. Best-effort; never raises."""
    try:
        fp, email, sub_obj = _referral_card_fingerprint_and_email(session_obj, sub_id, customer_id)
        # Always record the signup fingerprint/email so future signups can be deduped.
        try:
            database.db_signup_payment_method_record(tenant_id, fp, email)
        except Exception:
            pass

        code = (meta.get("referral_code") or "").strip().upper()
        if not code:
            return
        rc = database.db_referral_code_get_by_code(code, active_only=True)
        if not rc:
            deps.audit_log(
                "stripe", "referral_code_invalid", resource_type="tenant",
                resource_id=tenant_id, details={"code": code}, request=request,
            )
            return
        red_id = database.db_referral_redemption_create(
            tenant_id, rc["id"], code, rc["referrer_name"], plan, sub_id
        )
        if not red_id:
            return
        database.db_referral_redemption_update(red_id, card_fingerprint=fp, signup_email=email)

        # Anti-abuse: a card or email already used by a DIFFERENT prior signup blocks the
        # free month (exclude our own just-recorded row via exclude_tenant_id).
        dup_card = bool(fp) and database.db_signup_fingerprint_seen(fp, exclude_tenant_id=tenant_id)
        dup_email = bool(email) and database.db_signup_email_seen(email, exclude_tenant_id=tenant_id)
        if dup_card or dup_email:
            reason = "duplicate_card" if dup_card else "duplicate_email"
            database.db_referral_redemption_update(red_id, status="flagged", flagged_reason=reason, free_month_granted=False)
            deps.audit_log(
                "stripe", "referral_redemption_flagged", resource_type="tenant",
                resource_id=tenant_id, details={"code": code, "reason": reason}, request=request,
            )
            return

        # Grant the free month by extending the Stripe trial to ~30 days from start, so
        # the customer is genuinely not charged. Anchored off the subscription start.
        from plans import REFERRAL_FREE_MONTH_DAYS

        now_ts = int(datetime.now(timezone.utc).timestamp())
        started = int(getattr(sub_obj, "created", 0) or now_ts) if sub_obj else now_ts
        trial_end = max(started, now_ts) + REFERRAL_FREE_MONTH_DAYS * 86400
        if trial_end <= now_ts + 60:
            trial_end = now_ts + REFERRAL_FREE_MONTH_DAYS * 86400
        stripe.Subscription.modify(sub_id, trial_end=trial_end, proration_behavior="none")
        database.db_referral_redemption_update(red_id, status="granted", free_month_granted=True)
        deps.audit_log(
            "stripe", "referral_free_month_granted", resource_type="tenant",
            resource_id=tenant_id, details={"code": code, "days": REFERRAL_FREE_MONTH_DAYS}, request=request,
        )
    except Exception as e:
        logger.exception("referral_checkout_processing_failed tenant=%s: %s", tenant_id, e)


def _process_referral_commission(invoice_obj, sub_id, request):
    """On a real paid invoice for a referred subscription, create the $200 signup bounty
    (once, on the first paid charge) and a 25%-of-plan-price commission for the month
    (capped at 12 months / 1 year). Idempotent via DB unique constraints. Never raises."""
    try:
        from plans import REFERRAL_SIGNUP_BOUNTY_CENTS, REFERRAL_MRR_MONTHS_CAP, referral_mrr_commission_cents

        red = database.db_referral_redemption_get_by_subscription(sub_id)
        if not red or red.get("status") not in ("granted", "converted"):
            return  # no redemption, or flagged → never earns a payout
        red_id = red["id"]
        # Use the tenant's CURRENT plan so upgrades/downgrades follow the price.
        tenant = database.db_tenant_get_by_id(red["tenant_id"]) if red.get("tenant_id") else None
        plan = (tenant or {}).get("plan") or red.get("plan_at_signup") or "starter"
        invoice_id = invoice_obj.get("id") or "unknown"
        now = datetime.now(timezone.utc)

        first_paid_dt = None
        if red.get("first_paid_at"):
            try:
                first_paid_dt = datetime.fromisoformat(red["first_paid_at"].replace("Z", "+00:00"))
            except Exception:
                first_paid_dt = None

        # First paid charge → set converted + create the $200 signup bounty (idempotent).
        if not first_paid_dt:
            database.db_referral_redemption_update(red_id, status="converted", first_paid_at=now)
            first_paid_dt = now
            database.db_referral_commission_insert(
                red_id, "signup_bounty", "signup", REFERRAL_SIGNUP_BOUNTY_CENTS,
                plan, red["code_snapshot"], red["referrer_name_snapshot"],
            )
            deps.audit_log(
                "stripe", "referral_bounty_earned", resource_type="tenant",
                resource_id=red.get("tenant_id"), details={"amount_cents": REFERRAL_SIGNUP_BOUNTY_CENTS}, request=request,
            )

        # Recurring 25% MRR for this paid month — capped at 12 entries / within 1 year.
        if first_paid_dt and now > first_paid_dt + timedelta(days=365):
            return
        if database.db_referral_commission_count_mrr(red_id) >= REFERRAL_MRR_MONTHS_CAP:
            return
        amount = referral_mrr_commission_cents(plan)
        inserted = database.db_referral_commission_insert(
            red_id, "mrr", invoice_id, amount, plan, red["code_snapshot"], red["referrer_name_snapshot"],
        )
        if inserted:
            deps.audit_log(
                "stripe", "referral_mrr_earned", resource_type="tenant",
                resource_id=red.get("tenant_id"), details={"amount_cents": amount, "invoice": invoice_id}, request=request,
            )
    except Exception as e:
        logger.exception("referral_commission_processing_failed sub=%s: %s", sub_id, e)


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
                # Mirror Stripe's real subscription state: a fresh signup is on a
                # 7-day trial ('trialing' + trial_end), which unlocks full Pro-tier
                # features. Hardcoding 'active' here previously dropped trial users
                # to their paid plan immediately.
                sub_status, trial_ends_at = _subscription_status_and_trial(sub_id)
                database.db_tenant_update_subscription(
                    tenant_id,
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=sub_id,
                    subscription_status=sub_status,
                    plan=plan,
                    trial_ends_at=trial_ends_at,
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
                # Referral: record the signup's card/email and (if a valid code) grant the
                # free month or flag for abuse. Runs after provisioning so a Stripe call
                # here can never delay number setup. Best-effort; never breaks the webhook.
                _process_referral_on_checkout(
                    obj, meta, tenant_id, sub_id, customer_id, plan, request
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
                # Prefer metadata.plan (set at checkout); for a Customer-Portal plan
                # switch there's no metadata, so derive the plan from the subscription's
                # line-item price. Falls back to None (leave plan untouched) only when the
                # price is unrecognized — never silently downgrades to starter.
                plan = meta.get("plan") or _subscription_plan_from_obj(obj)
                trial_ends_at = None
                t_end = obj.get("trial_end")
                if t_end:
                    from datetime import datetime, timezone

                    trial_ends_at = datetime.fromtimestamp(int(t_end), tz=timezone.utc)
                database.db_tenant_update_subscription(
                    tenant_id,
                    stripe_subscription_id=sub_id,
                    subscription_status=status,
                    plan=plan,
                    trial_ends_at=trial_ends_at,
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
        elif etype == "invoice.payment_succeeded":
            # A real (non-trial) payment cleared → referral commission(s) may be due.
            amount_paid = obj.get("amount_paid") or 0
            inv_sub_id = obj.get("subscription")
            if amount_paid > 0 and inv_sub_id:
                _process_referral_commission(obj, inv_sub_id, request)
    except Exception as e:
        logger.exception("stripe_webhook handler error event_type=%s: %s", etype, e)
        # Record + alert: a swallowed Stripe failure can mean a missed cancellation,
        # un-released number, or unrecorded payout — never let it vanish into logs.
        try:
            import alerts

            alerts.notify_failure("stripe", etype, (evt.get("id") if isinstance(evt, dict) else None), str(e))
        except Exception:
            pass
    return {"received": True}
