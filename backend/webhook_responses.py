"""
Twilio webhook responses for subscription enforcement (voice + SMS).
"""

from __future__ import annotations

import logging
from typing import Optional

from subscription_access import webhook_access_denial_reason

_log = logging.getLogger("nuvatra")

VOICE_SUBSCRIPTION_LAPSED_MESSAGE = (
    "Thank you for calling. This line is temporarily unavailable. "
    "Please try again later or visit our website. Goodbye."
)

SMS_SUBSCRIPTION_LAPSED_MESSAGE = (
    "Thanks for your message. Text messaging for this business is temporarily unavailable. "
    "Please call us instead. Reply STOP to opt out."
)


def subscription_denied_voice_twiml() -> str:
    """Valid TwiML: brief message then hangup (no silence)."""
    try:
        from twilio.twiml.voice_response import VoiceResponse
    except ImportError:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<Response><Say voice=\"alice\">{VOICE_SUBSCRIPTION_LAPSED_MESSAGE}</Say><Hangup/></Response>"
        )
    vr = VoiceResponse()
    vr.say(VOICE_SUBSCRIPTION_LAPSED_MESSAGE, voice="alice")
    vr.hangup()
    return str(vr)


def log_webhook_subscription_denied(
    *,
    channel: str,
    reason: str,
    tenant: Optional[dict],
    request_id: Optional[str] = None,
) -> None:
    client_prefix = ""
    if tenant and tenant.get("client_id"):
        client_prefix = str(tenant["client_id"])[:12]
    plan = (tenant or {}).get("plan") or ""
    status = (tenant or {}).get("subscription_status") or ""
    _log.info(
        "[AUTH] webhook_subscription_denied channel=%s reason=%s client_id_prefix=%s plan=%s status=%s request_id=%s",
        channel,
        reason,
        client_prefix or "(none)",
        plan,
        status,
        request_id or "",
    )


def check_webhook_tenant_access(
    tenant: Optional[dict],
    *,
    channel: str,
    request_id: Optional[str] = None,
) -> bool:
    """
    Return True if webhook may proceed; False if subscription/tenant blocks service.

    Uses the same rules as require_active_subscription (via subscription_access).
    """
    reason = webhook_access_denial_reason(tenant)
    if reason:
        log_webhook_subscription_denied(
            channel=channel, reason=reason, tenant=tenant, request_id=request_id
        )
        return False
    return True
