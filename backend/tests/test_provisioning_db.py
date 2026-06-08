"""Provisioning job/task persistence layer."""

from __future__ import annotations

import json
from unittest.mock import patch

import database


def _mock_conn():
    return patch.object(database, "_get_conn")


def test_job_create_inserts_pending():
    with _mock_conn() as mc:
        cur = mc.return_value.cursor.return_value
        ok = database.db_provisioning_job_create("job-1", "admin-user", 60)
        assert ok is True
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO provisioning_jobs" in sql
        assert "'pending'" in sql
        assert params == ("job-1", "admin-user", 60)


def test_task_create_returns_id():
    with _mock_conn() as mc:
        cur = mc.return_value.cursor.return_value
        cur.fetchone.return_value = (42,)
        tid = database.db_provisioning_task_create(
            "job-1", "acme", name="Acme", email="o@acme.com", area_code="415", plan="growth"
        )
        assert tid == 42
        params = cur.execute.call_args[0][1]
        assert params == ("job-1", "acme", "Acme", "o@acme.com", "415", "growth")


def test_task_save_serializes_steps_and_increments_attempts():
    with _mock_conn() as mc:
        cur = mc.return_value.cursor.return_value
        database.db_provisioning_task_save(
            7, status="failed", steps_done=["tenant_created", "number_purchased"],
            phone_e164="+14155550001", error="clerk down",
        )
        sql, params = cur.execute.call_args[0]
        assert "attempts=attempts+1" in sql  # default: bump attempts
        assert params[0] == "failed"
        assert json.loads(params[1]) == ["tenant_created", "number_purchased"]
        assert params[2] == "+14155550001"
        assert params[3] == "clerk down"


def test_tasks_for_job_only_unfinished_filters():
    with _mock_conn() as mc:
        cur = mc.return_value.cursor.return_value
        cur.fetchall.return_value = []
        database.db_provisioning_tasks_for_job("job-1", only_unfinished=True)
        sql = cur.execute.call_args[0][0]
        assert "status <> 'done'" in sql


def test_task_row_parsing_handles_json_string_and_list():
    row = (1, "job-1", "acme", "Acme", "o@acme.com", "415", "free", "done",
           '["tenant_created"]', "+14155550001", None, 1)
    parsed = database._row_to_provisioning_task(row)
    assert parsed["steps_done"] == ["tenant_created"]
    assert parsed["client_id"] == "acme"
    assert parsed["phone_e164"] == "+14155550001"


def test_job_get_returns_none_when_missing():
    with _mock_conn() as mc:
        cur = mc.return_value.cursor.return_value
        cur.fetchone.return_value = None
        assert database.db_provisioning_job_get("nope") is None
