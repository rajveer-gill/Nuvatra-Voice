"""Outbound SMS via Twilio, plus E.164 normalization.

send_sms is shared across many domains (appointments, cron, SMS/phone webhooks),
so it lives here rather than in main.py. It reads the Twilio client singleton as
runtime.twilio_client and records usage / audit through database and deps.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import database
import deps
import runtime
from observability import sms_debug, sms_info, sms_trace
from security.redaction import mask_phone_e164

logger = logging.getLogger("nuvatra")

# From number for SMS — env-derived and immutable after process start.
TWILIO_SMS_FROM = os.getenv("TWILIO_SMS_FROM") or os.getenv("TWILIO_PHONE_NUMBER") or ""


def _phone_to_e164(phone: str) -> Optional[str]:
    """Convert to E.164 for Twilio SMS (e.g. +15551234567). Returns None if too short."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) >= 10:
        return f"+{digits}"
    return None


def send_sms(
    to_phone: str,
    body: str,
    from_override: Optional[str] = None,
    *,
    force: bool = False,
) -> bool:
    """Send SMS via Twilio. from_override: use this number as From (for multi-tenant replies from business number).
    Records usage via db_usage_increment_sms when client_id is set.
    If force=True, skip per-tenant opt-out check (STOP/START/HELP confirmations only).
    """
    if not runtime.twilio_client:
        sms_info("outbound_skipped", reason="twilio_not_configured")
        return False
    from_num = (from_override or TWILIO_SMS_FROM or "").strip()
    if not from_num:
        sms_info(
            "outbound_skipped",
            reason="from_number_missing",
            from_override_set=bool(from_override),
            twilio_sms_from_set=bool(TWILIO_SMS_FROM),
        )
        return False
    e164 = _phone_to_e164(to_phone or "")
    if not e164:
        sms_info("outbound_skipped", reason="invalid_recipient_phone")
        return False
    if runtime.USE_DB and not force:
        cid = database._client_id()
        if cid and cid != "default":
            if database.db_sms_opt_out_is_blocked(e164, cid):
                to_masked = mask_phone_e164(e164)
                sms_info(
                    "outbound_skipped",
                    reason="recipient_opted_out",
                    client_id_prefix=cid[:12],
                    to_masked=to_masked,
                )
                return False
    to_masked = mask_phone_e164(e164)
    sms_debug(
        "outbound_attempt",
        from_num=from_num,
        to_masked=to_masked,
        body_len=len(body or ""),
        force=force,
    )
    sms_trace(
        "outbound_attempt",
        from_num=from_num,
        to_masked=to_masked,
        body_len=len(body or ""),
        force=force,
    )
    last_err = None
    for attempt in range(3):
        try:
            msg = runtime.twilio_client.messages.create(
                from_=from_num, to=e164, body=body
            )
            sid = getattr(msg, "sid", None) or getattr(msg, "id", None)
            sms_info(
                "outbound_twilio_ok",
                message_sid=sid,
                to_masked=to_masked,
                body_len=len(body or ""),
            )
            # Record SMS usage for billing (graceful degradation)
            if runtime.USE_DB:
                cid = database._client_id()
                if cid and cid != "default":
                    try:
                        month = datetime.now(timezone.utc).strftime("%Y-%m")
                        database.db_usage_increment_sms(cid, month)
                    except Exception as e:
                        logger.error("SMS usage increment failed: %s", e)
            deps.audit_log(
                "sms",
                "outbound_sent",
                resource_type="message",
                resource_id=str(sid) if sid else None,
                client_id=database._client_id() if runtime.USE_DB else None,
                details={
                    "to_masked": to_masked,
                    "from_masked": mask_phone_e164(from_num),
                    "body_len": len(body or ""),
                    "body_sha256": hashlib.sha256((body or "").encode("utf-8")).hexdigest(),
                    "force": bool(force),
                },
            )
            return True
        except Exception as e:
            last_err = e
            logger.warning(
                "[SMS] outbound_twilio_retry attempt=%s error=%s to_masked=%s",
                attempt + 1,
                e,
                to_masked,
            )
            if attempt < 2:
                time.sleep(2**attempt)
    sms_info("outbound_failed_after_retries", error=str(last_err), to_masked=to_masked)
    deps.audit_log(
        "sms",
        "outbound_failed",
        resource_type="message",
        client_id=database._client_id() if runtime.USE_DB else None,
        details={
            "to_masked": to_masked,
            "from_masked": mask_phone_e164(from_num),
            "body_len": len(body or ""),
            "body_sha256": hashlib.sha256((body or "").encode("utf-8")).hexdigest(),
            "error": str(last_err)[:240] if last_err else None,
        },
    )
    return False
