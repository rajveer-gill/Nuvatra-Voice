"""Feedback API: POST /api/feedback (any tenant) + GET /api/feedback (admin).

Submissions are stored durably and emailed to the operator best-effort; a failing email
never fails the request, and the category is normalized to a safe value.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import database
import deps
import email_notify
from routers import feedback


def _req():
    req = MagicMock()
    req.headers.get.return_value = "pytest-agent"
    return req


def _wire(monkeypatch, *, insert_id=7, email_result=True, email_raises=False):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: "test")
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    inserts = []

    def _fake_insert(**kwargs):
        inserts.append(kwargs)
        return insert_id

    monkeypatch.setattr(database, "db_feedback_insert", _fake_insert)
    emails = []

    def _fake_email(subject, html_body, text_body=None):
        emails.append((subject, html_body))
        if email_raises:
            raise RuntimeError("smtp down")
        return email_result

    monkeypatch.setattr(email_notify, "send_operator_alert", _fake_email)
    return inserts, emails


def test_submit_feedback_stores_and_emails(monkeypatch):
    inserts, emails = _wire(monkeypatch)
    result = feedback.submit_feedback(
        feedback.FeedbackBody(category="bug", message="  Booking button is broken  ", email="u@x.com"),
        request=_req(),
        tenant={"client_id": "test"},
    )
    assert result == {"success": True, "id": 7}
    assert len(inserts) == 1
    assert inserts[0]["category"] == "bug"
    assert inserts[0]["message"] == "Booking button is broken"  # trimmed
    assert inserts[0]["client_id"] == "test"
    assert inserts[0]["user_email"] == "u@x.com"
    assert len(emails) == 1
    assert "Booking button is broken" in emails[0][1]


def test_submit_feedback_normalizes_bad_category(monkeypatch):
    inserts, _ = _wire(monkeypatch)
    feedback.submit_feedback(
        feedback.FeedbackBody(category="spam", message="hi"),
        request=_req(),
        tenant={"client_id": "test"},
    )
    assert inserts[0]["category"] == "other"


def test_submit_feedback_blank_message_400(monkeypatch):
    _wire(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        feedback.submit_feedback(
            feedback.FeedbackBody(category="idea", message="   "),
            request=_req(),
            tenant={"client_id": "test"},
        )
    assert exc.value.status_code == 400


def test_submit_feedback_survives_email_failure(monkeypatch):
    _wire(monkeypatch, email_raises=True)
    result = feedback.submit_feedback(
        feedback.FeedbackBody(category="other", message="just a note"),
        request=_req(),
        tenant={"client_id": "test"},
    )
    # Email blew up, but the submission was still stored and the request succeeds.
    assert result["success"] is True
    assert result["id"] == 7


def test_submit_feedback_without_db_still_succeeds(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr("runtime.USE_DB", False)
    result = feedback.submit_feedback(
        feedback.FeedbackBody(category="bug", message="something"),
        request=_req(),
        tenant={"client_id": "test"},
    )
    assert result["success"] is True
    assert result["id"] is None


def test_list_feedback_returns_stored(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    rows = [{"id": 1, "category": "bug", "message": "x"}]
    monkeypatch.setattr(database, "db_feedback_get_all", lambda limit=200: rows)
    result = feedback.list_feedback(_admin_user_id="admin-1")
    assert result == {"feedback": rows}
