"""Tests for operator alerting, the failed-events incident log, the health-digest cron,
and the admin system-health endpoints."""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


# --- alerts: throttling + best-effort ---

def test_report_critical_throttles_repeats(monkeypatch):
    import alerts

    alerts._last_alert_at.clear()
    monkeypatch.setenv("ALERT_THROTTLE_SECONDS", "900")
    sent = []
    monkeypatch.setattr(alerts, "_send_alert_sms", lambda text: sent.append(("sms", text)) or True)
    with patch("email_notify.send_operator_alert", lambda *a, **k: sent.append(("email", a)) or True):
        alerts.report_critical("k1", "Boom", "first")
        alerts.report_critical("k1", "Boom", "second")  # throttled — same key
    emails = [s for s in sent if s[0] == "email"]
    assert len(emails) == 1  # second suppressed by throttle


def test_report_critical_never_raises(monkeypatch):
    import alerts

    alerts._last_alert_at.clear()
    # Make the email path blow up; report_critical must swallow it.
    with patch("email_notify.send_operator_alert", side_effect=RuntimeError("smtp down")):
        monkeypatch.setattr(alerts, "_send_alert_sms", lambda text: True)
        alerts.report_critical("k2", "Subject", "msg")  # should not raise


def test_alert_sms_skips_when_unconfigured(monkeypatch):
    import alerts

    monkeypatch.delenv("OPERATOR_ALERT_SMS", raising=False)
    assert alerts._send_alert_sms("hi") is False


def test_notify_failure_records_and_alerts(monkeypatch):
    import alerts
    import database

    alerts._last_alert_at.clear()
    recorded = {}
    monkeypatch.setattr(
        database, "db_failed_event_insert",
        lambda source, et, ref, err, payload=None: recorded.update(source=source, et=et, ref=ref, err=err) or 1,
    )
    calls = []
    monkeypatch.setattr(alerts, "report_critical", lambda *a, **k: calls.append((a, k)))
    alerts.notify_failure("stripe", "checkout.session.completed", "evt_1", "kaboom")
    assert recorded["source"] == "stripe"
    assert recorded["err"] == "kaboom"
    assert calls  # alert fired


# --- health-digest cron ---

def test_health_digest_requires_secret(client):
    resp = client.post("/api/cron/health-digest")
    assert resp.status_code in (401, 503)


def test_health_digest_healthy(client, monkeypatch):
    import database
    import runtime
    from routers import cron

    monkeypatch.setattr(runtime, "USE_DB", True)
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    monkeypatch.setattr(cron, "_verify_cron_secret", lambda r: True)
    monkeypatch.setattr(database, "db_cron_run_start", lambda j: 1)
    monkeypatch.setattr(database, "db_cron_run_finish", lambda *a, **k: True)
    monkeypatch.setattr(database, "db_ping", lambda: True)
    monkeypatch.setattr(cron, "_stale_daily_crons", lambda: [])
    monkeypatch.setattr(database, "db_failed_events_unresolved_count", lambda: 0)
    monkeypatch.setattr(database, "db_tenant_list_all", lambda: [])
    monkeypatch.setattr(database, "db_referral_commissions_list_all", lambda include_paid=True: [])
    emails, crits = [], []
    with patch("email_notify.send_operator_alert", lambda *a, **k: emails.append(a) or True):
        with patch("alerts.report_critical", lambda *a, **k: crits.append(a)):
            resp = client.post("/api/cron/health-digest", headers={"X-Cron-Secret": "s3cret"})
    assert resp.status_code == 200
    assert resp.json()["healthy"] is True
    assert len(emails) == 1  # heartbeat email always sent
    assert crits == []       # no SMS escalation when healthy


def test_health_digest_escalates_on_problems(client, monkeypatch):
    import database
    import runtime
    from routers import cron

    monkeypatch.setattr(runtime, "USE_DB", True)
    monkeypatch.setattr(cron, "_verify_cron_secret", lambda r: True)
    monkeypatch.setattr(database, "db_cron_run_start", lambda j: 1)
    monkeypatch.setattr(database, "db_cron_run_finish", lambda *a, **k: True)
    monkeypatch.setattr(database, "db_ping", lambda: True)
    monkeypatch.setattr(cron, "_stale_daily_crons", lambda: ["export-snapshot"])
    monkeypatch.setattr(database, "db_failed_events_unresolved_count", lambda: 3)
    monkeypatch.setattr(database, "db_tenant_list_all", lambda: [])
    monkeypatch.setattr(database, "db_referral_commissions_list_all", lambda include_paid=True: [])
    crits = []
    with patch("email_notify.send_operator_alert", lambda *a, **k: True):
        with patch("alerts.report_critical", lambda *a, **k: crits.append(a)):
            resp = client.post("/api/cron/health-digest", headers={"X-Cron-Secret": "x"})
    assert resp.status_code == 200
    assert resp.json()["healthy"] is False
    assert crits  # escalated by SMS because there are problems


# --- admin failed-events endpoints ---

def test_test_alert_requires_admin(client):
    assert client.post("/api/admin/test-alert").status_code in (401, 403)


def test_test_alert_reports_channel_status(client, monkeypatch):
    import alerts
    import deps
    from deps import require_admin

    monkeypatch.setenv("OPERATOR_ALERT_EMAIL", "ops@example.com")
    monkeypatch.delenv("OPERATOR_ALERT_SMS", raising=False)
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(alerts, "_send_alert_sms", lambda text: False)
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        with patch("email_notify.send_operator_alert", lambda *a, **k: True):
            r = client.post("/api/admin/test-alert")
            assert r.status_code == 200
            body = r.json()
            assert body["email_sent"] is True
            assert body["email_target_set"] is True
            assert body["sms_sent"] is False
            assert body["sms_target_set"] is False
    finally:
        app.dependency_overrides.clear()


def test_failed_events_require_admin(client):
    assert client.get("/api/admin/failed-events").status_code in (401, 403)
    assert client.patch("/api/admin/failed-events/1", json={"resolved": True}).status_code in (401, 403)


def test_failed_events_list_and_resolve(client, monkeypatch):
    import database
    import deps
    import runtime
    from deps import require_admin

    monkeypatch.setattr(runtime, "USE_DB", True)
    monkeypatch.setattr(database, "db_failed_events_list",
                        lambda include_resolved=False: [{"id": 1, "source": "stripe", "error": "x", "resolved": False}])
    monkeypatch.setattr(database, "db_failed_events_unresolved_count", lambda: 1)
    resolved = {}
    monkeypatch.setattr(database, "db_failed_event_resolve", lambda eid: resolved.update(id=eid) or True)
    audits = []
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: audits.append(a))
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        lst = client.get("/api/admin/failed-events")
        assert lst.status_code == 200
        assert lst.json()["unresolved_count"] == 1
        res = client.patch("/api/admin/failed-events/1", json={"resolved": True})
        assert res.status_code == 200
        assert resolved["id"] == 1
        assert any(a[:2] == ("admin", "failed_event_resolved") for a in audits)
    finally:
        app.dependency_overrides.clear()
