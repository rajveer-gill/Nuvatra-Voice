"""A failed read must not be reported as an empty result.

Staging showed why: a connection-pool burst made db_org_list_all() return [] at
HTTP 200, and the console rendered "Group not found / 0 stores" for a group with
two stores, immediately after the admin changed that group's billing. Nothing had
been deleted. "Could not read" and "there is nothing" have to be distinguishable.
"""
import pytest

import database
import routers.admin as admin


def test_org_list_raises_when_no_connection(monkeypatch):
    monkeypatch.setattr(database, "_get_conn", lambda: None)
    with pytest.raises(database.DatabaseUnavailable):
        database.db_org_list_all.__wrapped__()


def test_tenant_list_raises_when_no_connection(monkeypatch):
    monkeypatch.setattr(database, "_get_conn", lambda: None)
    with pytest.raises(database.DatabaseUnavailable):
        database.db_tenant_list_all.__wrapped__()


def test_admin_orgs_endpoint_returns_503_not_an_empty_list(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(admin.runtime, "USE_DB", True, raising=False)

    def _unavailable():
        raise database.DatabaseUnavailable("pool exhausted")

    monkeypatch.setattr(admin.database, "db_org_list_all", _unavailable)
    with pytest.raises(HTTPException) as ei:
        admin.admin_list_orgs(_="admin")
    assert ei.value.status_code == 503
    # The admin needs to know their save was not the thing that went wrong.
    assert "nothing was changed" in str(ei.value.detail).lower()


def test_healthy_org_list_still_returns_its_rows(monkeypatch):
    monkeypatch.setattr(admin.runtime, "USE_DB", True, raising=False)
    monkeypatch.setattr(admin.database, "db_org_list_all",
                        lambda: [{"id": "o1", "name": "Lana Test Salon"}])
    out = admin.admin_list_orgs(_="admin")
    assert out["orgs"][0]["name"] == "Lana Test Salon"
    assert out["db_enabled"] is True


def test_pool_wait_absorbs_a_burst_instead_of_failing_instantly():
    """psycopg2's pool raises the moment it is empty. A short wait lets the
    connection that is about to be returned actually be used."""
    calls = {"n": 0}

    class _Pool:
        maxconn = 2

        def getconn(self):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("connection pool exhausted")
            return "conn"

    assert database._getconn_waiting(_Pool()) == "conn"
    assert calls["n"] == 3


def test_pool_wait_gives_up_rather_than_hanging(monkeypatch):
    monkeypatch.setattr(database, "_POOL_WAIT_SECONDS", 0.1)

    class _Pool:
        maxconn = 2

        def getconn(self):
            raise RuntimeError("connection pool exhausted")

    with pytest.raises(RuntimeError):
        database._getconn_waiting(_Pool())
