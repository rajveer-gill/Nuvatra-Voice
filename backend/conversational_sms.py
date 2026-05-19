"""
Conversational inbound SMS session limits (plan caps, billing-period scoped).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from billing_period import billing_period_for_tenant
from plans import get_plan_limits

_log = logging.getLogger("nuvatra")


@dataclass(frozen=True)
class ConversationalSmsReserveResult:
    allowed: bool
    is_new_session: bool
    session_count: int
    session_cap: int
    billing_period_key: str
    at_cap: bool
    over_cap: bool


def _normalize_phone_key(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return digits or (phone or "").strip()


def reserve_conversational_sms_session(tenant: dict, from_phone: str) -> ConversationalSmsReserveResult:
    """
    Reserve or continue a conversational SMS session before LLM cost.

    Uses DB locking when available; returns allowed=False when at cap.
    """
    from database import db_conversational_sms_reserve_session

    try:
        import main as m

        use_db = bool(getattr(m, "USE_DB", False))
    except ImportError:
        use_db = False

    limits = get_plan_limits(tenant)
    cap = int(limits.get("conversational_sms_sessions_cap") or 0)
    _, _, period_key = billing_period_for_tenant(tenant)
    phone_key = _normalize_phone_key(from_phone)
    client_id = (tenant.get("client_id") or "").strip()

    if not use_db or not client_id:
        return ConversationalSmsReserveResult(
            allowed=True,
            is_new_session=True,
            session_count=0,
            session_cap=cap,
            billing_period_key=period_key,
            at_cap=False,
            over_cap=False,
        )

    raw = db_conversational_sms_reserve_session(client_id, period_key, phone_key, cap)
    count = int(raw.get("session_count") or 0)
    allowed = bool(raw.get("allowed"))
    over_cap = not allowed and bool(raw.get("at_cap"))
    if over_cap:
        plan = limits.get("plan") or ""
        _log.info(
            "[USAGE] conversational_sms_session_cap_exceeded client_id_prefix=%s plan=%s cap=%s count=%s period=%s",
            client_id[:12],
            plan,
            cap,
            count,
            period_key,
        )
    return ConversationalSmsReserveResult(
        allowed=allowed,
        is_new_session=bool(raw.get("is_new_session")),
        session_count=count,
        session_cap=cap,
        billing_period_key=period_key,
        at_cap=bool(raw.get("at_cap")),
        over_cap=over_cap,
    )


def conversational_sms_cap_fallback_body(tenant: dict) -> str:
    """Polite SMS when conversational session cap is reached (no LLM)."""
    name = (tenant.get("name") or "our business").strip()
    phone = (tenant.get("twilio_phone_number") or "").strip()
    if phone:
        return (
            f"Thanks for texting {name}. We've reached our text limit for this billing period. "
            f"Please call us at {phone} and we'll be happy to help. Reply STOP to opt out."
        )
    return (
        f"Thanks for texting {name}. We've reached our text limit for this billing period. "
        "Please call us and we'll be happy to help. Reply STOP to opt out."
    )
