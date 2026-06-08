"""Appointment list must use explicit tenant client_id (not ambient context)."""

from __future__ import annotations

from unittest.mock import patch

import database


def test_db_appointments_in_date_range_excludes_cancelled_rejected():
    with patch.object(database, "_get_conn") as mock_conn:
        cur = mock_conn.return_value.cursor.return_value
        cur.fetchall.return_value = []
        database.db_appointments_in_date_range("2026-05-24", "2026-05-30", client_id="my-tenant")
        sql = cur.execute.call_args[0][0]
    assert "status NOT IN ('cancelled', 'rejected')" in sql


def test_db_appointments_get_all_uses_explicit_client_id():
    with patch.object(database, "_get_conn") as mock_conn:
        cur = mock_conn.return_value.cursor.return_value
        cur.fetchall.return_value = []
        database.db_appointments_get_all(client_id="my-tenant")
        params = cur.execute.call_args[0][1]
    assert params == ("my-tenant",)


def test_diagnostics_flags_env_mismatch():
    with patch.object(database, "_get_conn") as mock_conn:
        cur = mock_conn.return_value.cursor.return_value
        cur.fetchall.side_effect = [
            [("pending_customer", 2)],
            [],
        ]
        cur.fetchone.side_effect = [(0,), (5,)]
        with patch.dict("os.environ", {"CLIENT_ID": "other-env"}, clear=False):
            out = database.db_appointments_diagnostics("my-tenant")
    assert out["likely_mismatch"] is True
    assert out["env_client_id"] == "other-env"
    assert out["env_client_id_appointment_count"] == 5


def test_diagnostics_never_leaks_other_tenants():
    """Diagnostics must not enumerate other tenants' client_ids (cross-tenant leak)."""
    with patch.object(database, "_get_conn") as mock_conn:
        cur = mock_conn.return_value.cursor.return_value
        cur.fetchall.side_effect = [[("pending_customer", 2)], []]
        cur.fetchone.side_effect = [(3,)]
        with patch.dict("os.environ", {"CLIENT_ID": ""}, clear=False):
            out = database.db_appointments_diagnostics("my-tenant")
    assert "counts_by_client" not in out
    assert set(out["by_status"]) == {"pending_customer"}
    assert out["dashboard_client_id"] == "my-tenant"


def test_bind_tenant_db_context_sets_explicit_client_id():
    import main

    with patch.object(main, "set_request_client_id") as set_cid:
        cid = main._bind_tenant_db_context({"client_id": "my-tenant"})
    assert cid == "my-tenant"
    set_cid.assert_called_once_with("my-tenant")
