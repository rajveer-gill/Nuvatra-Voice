"""Caller-message vertical: MESSAGE: directive capture on calls + actionable dashboard routes.

Covers the directive parser/stripper, in-memory message storage, and the
mark-read / reply routes (including the silent-send-failure surfacing on reply).
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import booking_service
import conversation_service
import database
import deps
import runtime
import sms_service
import voice_service
from routers import core


# --- directive parsing / stripping -------------------------------------------

def test_parse_message_directive_extracts_body():
    txt = "Sure, I'll pass that along.\nMESSAGE: Caller wants a callback about pricing."
    assert voice_service.parse_message_directive(txt) == "Caller wants a callback about pricing."


def test_parse_message_directive_none_when_absent():
    assert voice_service.parse_message_directive("Sure, see you then!") is None
    assert voice_service.parse_message_directive("") is None


def test_strip_message_directive_removes_line():
    txt = "Sure, I'll let them know.\nMESSAGE: Wants a callback."
    cleaned = conversation_service._strip_message_directive_for_voice(txt)
    assert "MESSAGE:" not in cleaned
    assert "let them know" in cleaned


def test_no_transfer_fallback_does_not_ask_for_number():
    # We already have the caller's number from caller ID — the canned line that
    # elicits a message must not ask "what's the best number to reach you?".
    txt = conversation_service._NO_TRANSFER_FALLBACK_TEXT.lower()
    assert "take a message" in txt
    assert "number" not in txt
    assert "reach you" not in txt


# --- in-memory storage -------------------------------------------------------

def test_store_caller_message_inmemory(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", False)
    monkeypatch.setattr(runtime, "messages", [])
    call_data = {
        "client_id": "salon-test",
        "from_number": "+15551234567",
        "caller_memory": {"name": "Jordan"},
    }
    ok = conversation_service._store_caller_message(call_data, "Wants a callback ASAP")
    assert ok is True
    assert len(runtime.messages) == 1
    m = runtime.messages[0]
    assert m["caller_name"] == "Jordan"
    assert m["caller_phone"] == "+15551234567"
    assert m["urgency"] == "high"  # "asap" detected
    assert m["status"] == "unread"


def test_store_caller_message_empty_is_noop(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", False)
    monkeypatch.setattr(runtime, "messages", [])
    assert conversation_service._store_caller_message({}, "   ") is False
    assert runtime.messages == []


# --- routes ------------------------------------------------------------------

def _bind(monkeypatch):
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: "test")
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)


def test_mark_message_read(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch)
    captured = {}

    def fake_set(mid, status, client_id=None):
        captured["status"] = status
        return {"id": mid, "status": status, "caller_phone": "+15551110000"}

    monkeypatch.setattr(database, "db_messages_set_status", fake_set)
    result = core.mark_message_read(5, request=MagicMock(), read=True, tenant={"client_id": "test"})
    assert result["success"] is True
    assert captured["status"] == "read"
    assert result["message"]["status"] == "read"


def test_mark_message_read_404(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch)
    monkeypatch.setattr(database, "db_messages_set_status", lambda mid, status, client_id=None: None)
    with pytest.raises(HTTPException) as exc:
        core.mark_message_read(99, request=MagicMock(), read=True, tenant={"client_id": "test"})
    assert exc.value.status_code == 404


def test_reply_sends_sms_and_marks_read(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch)
    sent = []
    monkeypatch.setattr(
        database, "db_messages_get_by_id",
        lambda mid, client_id=None: {"id": mid, "caller_phone": "+15551110000", "status": "unread"},
    )
    monkeypatch.setattr(
        database, "db_messages_set_status",
        lambda mid, status, client_id=None: {"id": mid, "status": status, "caller_phone": "+15551110000"},
    )
    monkeypatch.setattr(booking_service, "_tenant_sms_from_number", lambda: "+15552220000")
    monkeypatch.setattr(sms_service, "send_sms", lambda to, body, from_override=None: sent.append(body) or True)

    result = core.reply_to_message(
        3, core.MessageReplyBody(text="On my way!"), request=MagicMock(), tenant={"client_id": "test"}
    )
    assert result["reply_sms_sent"] is True
    assert result["message"]["status"] == "read"
    assert sent == ["On my way!"]


def test_reply_surfaces_send_failure(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch)
    monkeypatch.setattr(
        database, "db_messages_get_by_id",
        lambda mid, client_id=None: {"id": mid, "caller_phone": "+15551110000", "status": "unread"},
    )
    monkeypatch.setattr(
        database, "db_messages_set_status",
        lambda mid, status, client_id=None: {"id": mid, "status": status, "caller_phone": "+15551110000"},
    )
    monkeypatch.setattr(booking_service, "_tenant_sms_from_number", lambda: "+15552220000")
    monkeypatch.setattr(sms_service, "send_sms", lambda to, body, from_override=None: False)

    result = core.reply_to_message(
        3, core.MessageReplyBody(text="hi"), request=MagicMock(), tenant={"client_id": "test"}
    )
    assert result["reply_sms_sent"] is False
    # Still resolved — the caller was attempted; dashboard shows the failure note.
    assert result["message"]["status"] == "read"


def test_reply_400_when_no_phone(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch)
    monkeypatch.setattr(
        database, "db_messages_get_by_id",
        lambda mid, client_id=None: {"id": mid, "caller_phone": "", "status": "unread"},
    )
    with pytest.raises(HTTPException) as exc:
        core.reply_to_message(
            3, core.MessageReplyBody(text="hi"), request=MagicMock(), tenant={"client_id": "test"}
        )
    assert exc.value.status_code == 400
