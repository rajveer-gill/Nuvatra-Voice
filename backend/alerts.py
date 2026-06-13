"""Operator alerting + incident logging.

`report_critical()` notifies the operator when something breaks — email (always) plus an
urgent SMS to a personal line (high-signal). Throttled per event-key so a flapping failure
can't spam you. `notify_failure()` additionally records the failure in the failed_events
table so it's visible + retryable in the admin panel.

Everything here is best-effort and never raises into the caller — alerting must never be
the thing that breaks a request.

Env:
  OPERATOR_ALERT_EMAIL    — where digests/alerts are emailed (see email_notify)
  OPERATOR_ALERT_SMS      — personal number to text on urgent failures (E.164)
  OPERATOR_ALERT_SMS_FROM — a Twilio number you own to send the alert from; if unset,
                            falls back to the A2P Messaging Service SID
  ALERT_THROTTLE_SECONDS  — min seconds between alerts for the same key (default 900)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger("nuvatra")

try:
    from twilio.rest import Client as TwilioClient
except ImportError:  # pragma: no cover
    TwilioClient = None  # type: ignore[misc, assignment]

# Per-key throttle (process-local). Render typically runs one instance; good enough to
# stop a tight failure loop from sending hundreds of texts.
_last_alert_at: dict[str, float] = {}


def _throttle_seconds() -> int:
    try:
        return int(os.getenv("ALERT_THROTTLE_SECONDS", "900"))
    except ValueError:
        return 900


def _should_send(event_key: str) -> bool:
    now = time.monotonic()
    last = _last_alert_at.get(event_key)
    if last is not None and now - last < _throttle_seconds():
        return False
    _last_alert_at[event_key] = now
    return True


def _send_alert_sms(text: str) -> bool:
    """Send an urgent SMS to the operator's personal line. Best-effort; returns success."""
    to = (os.getenv("OPERATOR_ALERT_SMS") or "").strip()
    if not to:
        return False
    if TwilioClient is None:
        return False
    acct = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    tok = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    if not (acct and tok):
        return False
    from_num = (os.getenv("OPERATOR_ALERT_SMS_FROM") or "").strip()
    msid = (os.getenv("TWILIO_A2P_MESSAGING_SERVICE_SID") or "").strip()
    body = text[:600]
    try:
        client = TwilioClient(acct, tok)
        if from_num:
            client.messages.create(to=to, from_=from_num, body=body)
        elif msid:
            client.messages.create(to=to, messaging_service_sid=msid, body=body)
        else:
            logger.warning("alert_sms_skipped reason=no_from_number")
            return False
        return True
    except Exception as e:
        logger.warning("alert_sms_failed: %s", e)
        return False


def report_critical(
    event_key: str, subject: str, message: str, *, details: Optional[dict] = None, sms: bool = True
) -> None:
    """Notify the operator of a serious problem. Email always; SMS for urgent ones.

    event_key throttles repeats (e.g. "cron_failed:process-overage"). Never raises."""
    try:
        if not _should_send(event_key):
            return
        full = message
        if details:
            try:
                lines = "\n".join(f"{k}: {v}" for k, v in details.items())
                full = f"{message}\n\n{lines}"
            except Exception:
                pass
        # Email (detailed)
        try:
            import email_notify

            html = f"<p><strong>{subject}</strong></p><pre>{full}</pre>"
            email_notify.send_operator_alert(f"[Call Surge] {subject}", html, full)
        except Exception as e:
            logger.warning("alert_email_failed: %s", e)
        # SMS (short, urgent)
        if sms:
            _send_alert_sms(f"[Call Surge] {subject} — {message}")
        logger.error("operator_alert key=%s subject=%s", event_key, subject)
    except Exception as e:  # pragma: no cover — alerting must never break the caller
        logger.warning("report_critical_failed: %s", e)


def notify_failure(
    source: str, event_type: Optional[str], ref: Optional[str], error: str,
    *, payload: Optional[dict] = None, sms: bool = True,
) -> None:
    """Record a swallowed failure in failed_events AND alert the operator. Best-effort.

    source: 'stripe' | 'twilio_voice' | 'twilio_sms' | 'cron' | 'task' | 'provision' ...
    """
    try:
        import database

        database.db_failed_event_insert(source, event_type, ref, error, payload)
    except Exception as e:
        logger.warning("failed_event_record_failed: %s", e)
    subject = f"{source} failure" + (f" ({event_type})" if event_type else "")
    msg = error if not ref else f"{error} [ref={ref}]"
    report_critical(f"failure:{source}:{event_type or ''}", subject, msg, details=payload, sms=sms)
