"""SMS conversation viewer: thread list, thread detail, and the dashboard
'Total Messages' count (total texts exchanged across all threads)."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import database
import deps
import runtime
from routers import core
from routers import analytics


def _bind(monkeypatch, has_messages=True):
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: (tenant or {}).get("client_id") or "test")
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(core, "get_plan_limits", lambda tenant: {"has_messages": has_messages})


def test_get_sms_threads_returns_list(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch)
    threads = [
        {"phone": "19259978995", "message_count": 4, "last_message": "See you then!",
         "last_role": "assistant", "appointment_id": 7, "updated_at": "2026-06-14T22:00:00+00:00"},
    ]
    captured = {}

    def fake_list(cid, search=None, limit=200):
        captured["cid"] = cid
        captured["search"] = search
        return threads

    monkeypatch.setattr(database, "db_sms_threads_list", fake_list)
    res = core.get_sms_threads(search="925", tenant={"client_id": "salon"})
    assert res["threads"] == threads
    assert captured["cid"] == "salon"
    assert captured["search"] == "925"


def test_get_sms_thread_returns_messages(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch)
    monkeypatch.setattr(database, "_normalize_phone", lambda p: "19259978995")
    monkeypatch.setattr(
        database,
        "db_sms_session_get",
        lambda phone, cid: {
            "messages": [
                {"role": "user", "content": "Hi, can I book a cut?"},
                {"role": "assistant", "content": "Of course! What day?"},
                {"role": "bogus"},  # missing content tolerated
            ],
            "appointment_id": 7,
            "updated_at": None,
        },
    )
    res = core.get_sms_thread(phone="+1 (925) 997-8995", tenant={"client_id": "salon"})
    assert res["phone"] == "19259978995"
    assert len(res["messages"]) == 3
    assert res["messages"][0] == {"role": "user", "content": "Hi, can I book a cut?"}
    assert res["messages"][2]["content"] == ""
    assert res["appointment_id"] == 7


def test_sms_threads_locked_on_starter(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch, has_messages=False)
    # Should not even hit the DB helper when locked.
    monkeypatch.setattr(database, "db_sms_threads_list", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not query")))
    res = core.get_sms_threads(search=None, tenant={"client_id": "salon", "plan": "starter"})
    assert res == {"threads": [], "locked": True}


def test_sms_thread_detail_403_on_starter(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch, has_messages=False)
    with pytest.raises(HTTPException) as exc:
        core.get_sms_thread(phone="+15550000000", tenant={"client_id": "salon", "plan": "starter"})
    assert exc.value.status_code == 403


def test_get_sms_thread_404_when_missing(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch)
    monkeypatch.setattr(database, "db_sms_session_get", lambda phone, cid: None)
    with pytest.raises(HTTPException) as exc:
        core.get_sms_thread(phone="+15550000000", tenant={"client_id": "salon"})
    assert exc.value.status_code == 404


def test_stats_total_messages_counts_texts_exchanged(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    _bind(monkeypatch)
    monkeypatch.setattr(database, "db_appointments_get_all", lambda client_id=None: [
        {"status": "pending"}, {"status": "accepted"}
    ])
    monkeypatch.setattr(database, "db_sms_messages_total", lambda cid: 9)
    monkeypatch.setattr(
        database, "db_appointments_diagnostics",
        lambda cid: {"by_status": {}, "env_client_id": None,
                     "env_client_id_appointment_count": None, "likely_mismatch": False},
    )
    monkeypatch.setattr(analytics, "system_info", lambda *a, **k: None)
    res = analytics.get_stats(tenant={"client_id": "salon"})
    assert res["total_messages"] == 9
    assert res["total_appointments"] == 2
    assert res["pending_appointments"] == 1
