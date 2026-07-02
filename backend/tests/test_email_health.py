"""Email-config health check: email_notify.config_status() + GET /api/health/email.

Booleans only — the endpoint must never echo secret values. Mirrors the real send logic:
a Resend key OR an SMTP host counts as a transport, plus a from-address, plus (for alerts)
an operator recipient.
"""

import email_notify
from routers import health

_ALL_EMAIL_VARS = (
    "RESEND_API_KEY",
    "SMTP_HOST",
    "APPOINTMENT_EMAIL_FROM",
    "RESEND_FROM",
    "OPERATOR_ALERT_EMAIL",
)


def _clear(monkeypatch):
    for v in _ALL_EMAIL_VARS:
        monkeypatch.delenv(v, raising=False)


def test_config_status_all_set_via_resend(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    monkeypatch.setenv("APPOINTMENT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("OPERATOR_ALERT_EMAIL", "ops@example.com")
    s = email_notify.config_status()
    assert s["resend_key"] and s["from_addr"] and s["operator_alert_to"]
    assert s["can_send"] is True
    assert s["feedback_alerts_ready"] is True
    assert all(isinstance(v, bool) for v in s.values())


def test_config_status_smtp_counts_as_transport(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("APPOINTMENT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("OPERATOR_ALERT_EMAIL", "ops@example.com")
    s = email_notify.config_status()
    assert s["resend_key"] is False
    assert s["can_send"] is True  # SMTP host is a valid transport
    assert s["feedback_alerts_ready"] is True


def test_config_status_missing_transport_not_ready(monkeypatch):
    _clear(monkeypatch)
    # From-address + recipient present, but no Resend key and no SMTP host.
    monkeypatch.setenv("APPOINTMENT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("OPERATOR_ALERT_EMAIL", "ops@example.com")
    s = email_notify.config_status()
    assert s["can_send"] is False
    assert s["feedback_alerts_ready"] is False


def test_config_status_missing_operator_recipient(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    monkeypatch.setenv("APPOINTMENT_EMAIL_FROM", "from@example.com")
    s = email_notify.config_status()
    assert s["can_send"] is True  # can send appointment emails
    assert s["operator_alert_to"] is False
    assert s["feedback_alerts_ready"] is False  # but not operator/feedback alerts


def test_health_email_endpoint_booleans_only(monkeypatch):
    _clear(monkeypatch)
    out = health.health_email()
    assert out["can_send"] is False
    assert all(isinstance(v, bool) for v in out.values())
    # No secret values leak through — every value is a plain bool.
    assert set(out.keys()) == {
        "resend_key",
        "smtp_host",
        "from_addr",
        "operator_alert_to",
        "can_send",
        "feedback_alerts_ready",
    }
