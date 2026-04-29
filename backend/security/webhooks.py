"""
Webhook signature verification for Twilio and Stripe.

All mutating webhooks should validate before parsing bodies or updating state.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import Request

logger = logging.getLogger("nuvatra.security")

try:
    from twilio.request_validator import RequestValidator
except ImportError:
    RequestValidator = None  # type: ignore[misc, assignment]


def validate_twilio_webhook(
    request: Request,
    form_data: dict,
    *,
    auth_token: Optional[str],
    twilio_available: bool,
) -> bool:
    """
    Validate X-Twilio-Signature. Returns True if valid, or if validation is skipped
    (no auth token / Twilio not installed) for backward-compatible dev setups.
    """
    token = (auth_token or "").strip()
    if not token:
        return True
    if not twilio_available or not RequestValidator:
        return True
    sig = request.headers.get("X-Twilio-Signature", "")
    if not sig:
        return False
    url = str(request.url)
    params = dict(form_data) if hasattr(form_data, "keys") else {k: v for k, v in form_data.items()}
    try:
        validator = RequestValidator(token)
        return bool(validator.validate(url, params, sig))
    except Exception as e:
        logger.warning("Twilio signature validation error: %s", e)
        return False


def verify_stripe_event(
    payload: bytes,
    sig_header: str,
    *,
    webhook_secret: str,
    stripe_module: Any,
) -> Tuple[Optional[Any], Optional[str]]:
    """
    Verify Stripe-Signature and return (event, None) or (None, error_detail).
    """
    secret = (webhook_secret or "").strip()
    if not secret:
        return None, "Webhook secret not configured"
    try:
        event = stripe_module.Webhook.construct_event(payload, sig_header, secret)
        return event, None
    except ValueError:
        return None, "Invalid payload"
    except stripe_module.SignatureVerificationError:
        return None, "Invalid signature"
