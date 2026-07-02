"""
Optional appointment confirmation emails via Resend (preferred) or SMTP.

Env:
  RESEND_API_KEY — Resend API key (https://resend.com)
  APPOINTMENT_EMAIL_FROM — verified sender, e.g. appointments@yourdomain.com
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD — fallback if Resend unset
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


def _from_address() -> str:
    return (os.getenv("APPOINTMENT_EMAIL_FROM") or os.getenv("RESEND_FROM") or "").strip()


def config_status() -> dict:
    """Booleans describing whether transactional email is configured on this (backend) host.

    Reflects the exact env this module uses to send — a Resend key OR an SMTP host counts as a
    transport. Values are booleans only; secret values are never returned. The marketing contact
    form runs on the frontend (Netlify) and is not observable from here."""
    resend = bool((os.getenv("RESEND_API_KEY") or "").strip())
    smtp = bool((os.getenv("SMTP_HOST") or "").strip())
    from_addr = bool(_from_address())
    operator_alert_to = bool((os.getenv("OPERATOR_ALERT_EMAIL") or "").strip())
    can_send = (resend or smtp) and from_addr
    return {
        "resend_key": resend,
        "smtp_host": smtp,
        "from_addr": from_addr,
        "operator_alert_to": operator_alert_to,
        "can_send": can_send,
        # Feedback / operator alerts need a transport, a sender, AND a recipient.
        "feedback_alerts_ready": can_send and operator_alert_to,
    }


def send_appointment_email(
    to: str,
    *,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> bool:
    """Send one transactional email. Returns True on success."""
    to_addr = (to or "").strip()
    if not to_addr or "@" not in to_addr:
        return False
    from_addr = _from_address()
    if not from_addr:
        logger.info("appointment_email_skipped reason=no_from_address to=%s", to_addr[:3] + "…")
        return False
    text = (text_body or "").strip() or _html_to_plain(html_body)
    if _send_via_resend(to_addr, from_addr, subject, html_body, text):
        return True
    return _send_via_smtp(to_addr, from_addr, subject, html_body, text)


def send_operator_alert(subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """Send an operational alert to the operator (e.g. a tenant crossing its usage cap).

    Recipient is OPERATOR_ALERT_EMAIL. No-op (returns False) when unset, so this is safe
    to call best-effort from a hot path. Reuses the same Resend/SMTP transport."""
    to_addr = (os.getenv("OPERATOR_ALERT_EMAIL") or "").strip()
    if not to_addr or "@" not in to_addr:
        logger.info("operator_alert_skipped reason=no_recipient")
        return False
    from_addr = _from_address()
    if not from_addr:
        logger.info("operator_alert_skipped reason=no_from_address")
        return False
    text = (text_body or "").strip() or _html_to_plain(html_body)
    if _send_via_resend(to_addr, from_addr, subject, html_body, text):
        return True
    return _send_via_smtp(to_addr, from_addr, subject, html_body, text)


def _html_to_plain(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").replace("&nbsp;", " ").strip()


def _send_via_resend(to: str, from_addr: str, subject: str, html: str, text: str) -> bool:
    key = (os.getenv("RESEND_API_KEY") or "").strip()
    if not key:
        return False
    try:
        import httpx

        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "from": from_addr,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
            timeout=20.0,
        )
        if r.status_code in (200, 201):
            logger.info("appointment_email_sent provider=resend to=%s", to.split("@")[0] + "@…")
            return True
        logger.warning("appointment_email_resend_failed status=%s body=%s", r.status_code, (r.text or "")[:200])
    except Exception as e:
        logger.warning("appointment_email_resend_error: %s", e, exc_info=True)
    return False


def _send_via_smtp(to: str, from_addr: str, subject: str, html: str, text: str) -> bool:
    host = (os.getenv("SMTP_HOST") or "").strip()
    if not host:
        return False
    port = int(os.getenv("SMTP_PORT") or "587")
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.ehlo()
            if port != 25:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to], msg.as_string())
        logger.info("appointment_email_sent provider=smtp to=%s", to.split("@")[0] + "@…")
        return True
    except Exception as e:
        logger.warning("appointment_email_smtp_error: %s", e, exc_info=True)
    return False


def format_appointment_email(
    *,
    kind: str,
    business_name: str,
    customer_name: str,
    date: str,
    time_ampm: str,
    service: str = "",
) -> tuple[str, str, str]:
    """Return (subject, html, text) for kind in submitted | confirmed."""
    name = (customer_name or "there").strip()
    biz = (business_name or "the business").strip()
    svc = f"<p><strong>Service:</strong> {service}</p>" if service and service != "—" else ""
    svc_t = f"\nService: {service}" if service and service != "—" else ""
    if kind == "confirmed":
        subject = f"Appointment confirmed — {biz}"
        html = f"""
        <p>Hi {name},</p>
        <p>Your appointment at <strong>{biz}</strong> is <strong>confirmed</strong>.</p>
        <p><strong>When:</strong> {date} at {time_ampm}</p>
        {svc}
        <p>Reply to the business text thread or call the shop if you need to change anything.</p>
        """
        text = (
            f"Hi {name},\n\nYour appointment at {biz} is confirmed.\n"
            f"When: {date} at {time_ampm}.{svc_t}\n\nReply by text or call if you need to change."
        )
    else:
        subject = f"We received your appointment request — {biz}"
        html = f"""
        <p>Hi {name},</p>
        <p>We received your appointment request at <strong>{biz}</strong> and sent it to the shop for approval.</p>
        <p><strong>Requested time:</strong> {date} at {time_ampm}</p>
        {svc}
        <p>We'll text you when they confirm.</p>
        """
        text = (
            f"Hi {name},\n\nWe received your request at {biz}.\n"
            f"Requested: {date} at {time_ampm}.{svc_t}\n\nWe'll text you when they confirm."
        )
    return subject, html.strip(), text.strip()
