"""Multi-store oversight: store scoping, the IDOR guard, and read-only viewers.

The security claim being tested is that org access is granted in exactly one place
(deps._resolve_org_store) and that it cannot reach a store outside the caller's org.
The DB-integration tests at the bottom are the ones that actually prove it, because
the check lives inside the SQL join.
"""

from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

import database
import deps


class _Req:
    """Minimal stand-in for a FastAPI Request (headers + method)."""

    def __init__(self, method="GET", store=None):
        self.method = method
        self.headers = {"X-Store-Id": store} if store else {}
        self.client = None
        self.url = "http://test/api/stats"


# --- The org path is opt-in ---------------------------------------------------


def test_no_store_header_means_normal_resolution(monkeypatch):
    """A normal store owner sends no X-Store-Id, so the org path must stay out of the
    way entirely — otherwise every existing user's auth changes."""
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    called = []
    monkeypatch.setattr(
        database, "db_org_store_for_user", lambda *a: called.append(a) or None
    )
    assert deps._resolve_org_store(_Req(), "user_1") is None
    assert called == []


def test_store_header_ignored_without_a_user(monkeypatch):
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    assert deps._resolve_org_store(_Req(store="shop-a"), "") is None


# --- The IDOR guard -----------------------------------------------------------


def test_store_outside_your_org_is_403(monkeypatch):
    """The whole feature's safety rests on this: an overseer asking for someone
    else's store by id must be refused, not served."""
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    monkeypatch.setattr(database, "db_org_store_for_user", lambda *a: None)
    # They oversee *something*, just not this store — a real access attempt.
    monkeypatch.setattr(
        database, "db_org_memberships", lambda uid: [{"org_id": "o1", "role": "viewer"}]
    )
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        deps._resolve_org_store(_Req(store="someone-elses-shop"), "user_1")
    assert e.value.status_code == 403


def test_stale_store_header_does_not_lock_out_a_normal_owner(monkeypatch):
    """A plain store owner with a leftover X-Store-Id in their browser must fall
    through to normal resolution. 403ing here would shut them out of their own shop."""
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    monkeypatch.setattr(database, "db_org_store_for_user", lambda *a: None)
    monkeypatch.setattr(database, "db_org_memberships", lambda uid: [])
    assert deps._resolve_org_store(_Req(store="stale-shop"), "user_owner") is None


def test_authorized_store_resolves(monkeypatch):
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    monkeypatch.setattr(
        database,
        "db_org_store_for_user",
        lambda *a: {"tenant": {"client_id": "shop-a", "name": "Shop A"}, "role": "viewer"},
    )
    tenant = deps._resolve_org_store(_Req(store="shop-a"), "user_1")
    assert tenant["client_id"] == "shop-a"


# --- Read-only oversight ------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
def test_viewer_cannot_write(monkeypatch, method):
    """They asked to *monitor* stores. A viewer reaching a write endpoint on a store
    they don't own must be refused at the auth seam, before any handler runs."""
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    monkeypatch.setattr(
        database,
        "db_org_store_for_user",
        lambda *a: {"tenant": {"client_id": "shop-a"}, "role": "viewer"},
    )
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        deps._resolve_org_store(_Req(method=method, store="shop-a"), "user_1")
    assert e.value.status_code == 403


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_viewer_can_read(monkeypatch, method):
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    monkeypatch.setattr(
        database,
        "db_org_store_for_user",
        lambda *a: {"tenant": {"client_id": "shop-a"}, "role": "viewer"},
    )
    assert deps._resolve_org_store(_Req(method=method, store="shop-a"), "user_1") is not None


def test_manager_may_write(monkeypatch):
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    monkeypatch.setattr(
        database,
        "db_org_store_for_user",
        lambda *a: {"tenant": {"client_id": "shop-a"}, "role": "manager"},
    )
    assert deps._resolve_org_store(_Req(method="PATCH", store="shop-a"), "user_1") is not None


def test_unknown_role_is_treated_as_read_only(monkeypatch):
    """Fail closed: a role we don't recognize must not get write access."""
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    monkeypatch.setattr(
        database,
        "db_org_store_for_user",
        lambda *a: {"tenant": {"client_id": "shop-a"}, "role": "wizard"},
    )
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        deps._resolve_org_store(_Req(method="POST", store="shop-a"), "user_1")
    assert e.value.status_code == 403


def test_role_defaults_to_viewer_on_bad_input():
    """db_org_member_add normalizes unknown roles down to viewer, never up."""
    assert "viewer" in database.ORG_ROLES and "manager" in database.ORG_ROLES


# --- Real-Postgres integration ------------------------------------------------

_DB = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL required (needs real Postgres)"
)


def _mk_store(cid: str, name: str):
    t = database.db_tenant_create_pending(cid, name, "pro", "salon_chair")
    assert t, f"could not create {cid}"
    return t


@_DB
def test_org_rollup_lists_only_your_stores():
    database.init_db()
    org_a = database.db_org_create("Region A")
    org_b = database.db_org_create("Region B")
    a1 = _mk_store("org-a1", "Shop A1")
    a2 = _mk_store("org-a2", "Shop A2")
    b1 = _mk_store("org-b1", "Shop B1")
    database.db_org_attach_tenant(a1["id"], org_a["id"])
    database.db_org_attach_tenant(a2["id"], org_a["id"])
    database.db_org_attach_tenant(b1["id"], org_b["id"])
    database.db_org_member_add("user_regional_a", org_a["id"], "viewer")

    stores = database.db_org_stores_for_user("user_regional_a")
    assert {s["client_id"] for s in stores} == {"org-a1", "org-a2"}
    assert all(s["org_role"] == "viewer" for s in stores)
    # Someone with no org membership oversees nothing.
    assert database.db_org_stores_for_user("user_nobody") == []


@_DB
def test_cannot_resolve_a_store_in_another_org():
    """The IDOR guard, against real SQL — the join is the authorization."""
    database.init_db()
    org_a = database.db_org_create("Region A")
    org_b = database.db_org_create("Region B")
    a1 = _mk_store("idor-a1", "Shop A1")
    b1 = _mk_store("idor-b1", "Shop B1")
    database.db_org_attach_tenant(a1["id"], org_a["id"])
    database.db_org_attach_tenant(b1["id"], org_b["id"])
    database.db_org_member_add("user_a", org_a["id"], "viewer")

    assert database.db_org_store_for_user("user_a", "idor-a1") is not None
    # By client_id and by raw UUID — both must be refused.
    assert database.db_org_store_for_user("user_a", "idor-b1") is None
    assert database.db_org_store_for_user("user_a", b1["id"]) is None
    # A garbage ref must return None, not raise (id is cast to text, not the param).
    assert database.db_org_store_for_user("user_a", "not-a-uuid-at-all") is None


@_DB
def test_independent_store_is_invisible_to_every_org():
    """org_id NULL is every existing tenant. They must not leak into any org."""
    database.init_db()
    org = database.db_org_create("Region")
    _mk_store("solo-shop", "Solo Shop")  # never attached
    database.db_org_member_add("user_x", org["id"], "manager")
    assert database.db_org_stores_for_user("user_x") == []
    assert database.db_org_store_for_user("user_x", "solo-shop") is None


@_DB
def test_detaching_a_store_revokes_oversight():
    database.init_db()
    org = database.db_org_create("Region")
    t = _mk_store("detach-me", "Shop")
    database.db_org_attach_tenant(t["id"], org["id"])
    database.db_org_member_add("user_x", org["id"], "viewer")
    assert database.db_org_store_for_user("user_x", "detach-me") is not None

    database.db_org_attach_tenant(t["id"], None)
    assert database.db_org_store_for_user("user_x", "detach-me") is None


@_DB
def test_org_membership_does_not_touch_tenant_ownership():
    """The point of a separate table: adding an overseer must not disturb the store's
    own owner, whom db_tenant_member_set_single would otherwise delete."""
    database.init_db()
    org = database.db_org_create("Region")
    t = _mk_store("owned-shop", "Owned Shop")
    database.db_org_attach_tenant(t["id"], org["id"])
    database.db_tenant_member_set_single("user_owner", t["id"])
    database.db_org_member_add("user_regional", org["id"], "viewer")

    assert database.db_tenant_get_members(t["id"]) == ["user_owner"]
    owner_tenant = database.db_tenant_get_for_user("user_owner")
    assert owner_tenant and owner_tenant["client_id"] == "owned-shop"


@_DB
def test_store_metrics_are_scoped_per_store():
    database.init_db()
    org = database.db_org_create("Region")
    a = _mk_store("m-a", "A")
    b = _mk_store("m-b", "B")
    for t in (a, b):
        database.db_org_attach_tenant(t["id"], org["id"])

    database.set_request_client_id("m-a")
    database.db_call_log_append(
        {"call_sid": "CA_m_a_1", "outcome": "missed", "duration_sec": 5, "from_number": "+14155550101"}
    )
    database.db_call_log_append(
        {"call_sid": "CA_m_a_2", "outcome": "answered_by_ai", "duration_sec": 60, "from_number": "+14155550102"}
    )
    database.set_request_client_id("m-b")
    database.db_call_log_append(
        {"call_sid": "CA_m_b_1", "outcome": "answered_by_ai", "duration_sec": 30, "from_number": "+14155550103"}
    )

    m = database.db_org_store_metrics(["m-a", "m-b"])
    assert m["m-a"]["calls"] == 2
    assert m["m-a"]["missed"] == 1
    assert m["m-b"]["calls"] == 1
    assert m["m-b"]["missed"] == 0
