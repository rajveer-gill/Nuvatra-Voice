"""An admin can open any store's dashboard, and it is written down every time.

Setting a customer up used to mean adding yourself to their group — a real
membership row, easy to create and easy to forget to remove. This resolves from the
admin allowlist instead: nothing is created, and access disappears the moment the
user leaves ADMIN_CLERK_USER_IDS.

It grants no new trust. The admin panel can already delete a tenant outright. What
it must not do is happen quietly, so every request through this path is audited —
"who looked at this customer's data and when" is the question that gets asked
afterwards, and the answer has to exist.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import database
import deps


class _Req:
    def __init__(self, method="GET", store=None):
        self.method = method
        self.headers = {"X-Store-Id": store} if store else {}
        self.client = None
        self.url = "http://test/api/appointments"


_TENANT = {"id": "t-9", "client_id": "gill-olympia", "name": "HairMasters Olympia"}


def _setup(monkeypatch, *, admin_ids="user_admin", org_hit=None, audits=None):
    monkeypatch.setenv("ADMIN_CLERK_USER_IDS", admin_ids)
    monkeypatch.setattr(deps.runtime, "USE_DB", True)
    monkeypatch.setattr(database, "db_org_store_for_user", lambda *a: org_hit)
    monkeypatch.setattr(database, "db_org_memberships", lambda uid: [])
    monkeypatch.setattr(
        database, "db_tenant_get_by_client_id",
        lambda ref: _TENANT if ref == "gill-olympia" else None,
    )
    monkeypatch.setattr(database, "db_tenant_get_by_id", lambda ref: None)
    monkeypatch.setattr(database, "set_request_client_id", lambda cid: None)
    # audit_log takes actor_type and action positionally, so capture both.
    monkeypatch.setattr(
        deps, "audit_log",
        lambda *a, **k: (
            audits.append({"actor_type": a[0], "action": a[1], **k})
            if audits is not None
            else None
        ),
    )


def test_an_admin_can_open_any_store(monkeypatch):
    _setup(monkeypatch)
    tenant = deps._resolve_org_store(_Req(store="gill-olympia"), "user_admin")
    assert tenant["client_id"] == "gill-olympia"


def test_every_request_is_audited_not_just_the_first(monkeypatch):
    """A single "opened the dashboard" entry would say nothing about what happened
    next."""
    audits: list = []
    _setup(monkeypatch, audits=audits)
    for _ in range(3):
        deps._resolve_org_store(_Req(store="gill-olympia"), "user_admin")
    assert len(audits) == 3
    assert all(a["action"] == "admin_store_access" for a in audits)
    assert audits[0]["actor_id"] == "user_admin"
    assert audits[0]["client_id"] == "gill-olympia"


def test_an_admin_may_change_things(monkeypatch):
    """Support access exists to DO the setup, so it isn't read-only."""
    _setup(monkeypatch)
    for method in ("POST", "PATCH", "DELETE"):
        tenant = deps._resolve_org_store(_Req(method=method, store="gill-olympia"), "user_admin")
        assert tenant["client_id"] == "gill-olympia"


def test_a_normal_user_is_unaffected(monkeypatch):
    """The regression guard: a store owner with a stale header must still fall through
    to normal resolution rather than being handed someone else's store."""
    _setup(monkeypatch)
    assert deps._resolve_org_store(_Req(store="gill-olympia"), "user_someone") is None


def test_a_non_admin_org_member_still_gets_403(monkeypatch):
    monkeypatch.setattr(database, "db_org_memberships", lambda uid: [{"org_id": "o1"}])
    _setup(monkeypatch)
    monkeypatch.setattr(database, "db_org_memberships", lambda uid: [{"org_id": "o1"}])
    with pytest.raises(HTTPException) as e:
        deps._resolve_org_store(_Req(store="gill-olympia"), "user_someone")
    assert e.value.status_code == 403


def test_admin_not_configured_grants_nobody(monkeypatch):
    """An empty allowlist must not mean "everyone"."""
    _setup(monkeypatch, admin_ids="")
    assert deps._resolve_org_store(_Req(store="gill-olympia"), "user_admin") is None
    assert deps.is_admin_user("") is False


def test_an_unknown_store_is_not_conjured(monkeypatch):
    """Admin or not, a store that doesn't exist isn't access to anything."""
    _setup(monkeypatch)
    assert deps._resolve_org_store(_Req(store="no-such-store"), "user_admin") is None


def test_a_real_membership_still_wins(monkeypatch):
    """When the admin genuinely owns the store, the normal path handles it and the
    support-access audit doesn't fire."""
    audits: list = []
    _setup(
        monkeypatch,
        org_hit={"tenant": _TENANT, "role": "manager"},
        audits=audits,
    )
    tenant = deps._resolve_org_store(_Req(store="gill-olympia"), "user_admin")
    assert tenant["client_id"] == "gill-olympia"
    assert not [a for a in audits if a.get("action") == "admin_store_access"]
