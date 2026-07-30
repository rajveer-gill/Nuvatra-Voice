"""Every account is an org.

Signup creates an org holding one store, and the signer-up manages it. One location or
thirty-four is the same shape, so opening a second location is "add a store" rather
than a migration onto a different kind of account.

The behavioral promise these pin down: a one-location owner never sees a store picker.
"""

from __future__ import annotations

import os

import pytest

import database

_DB = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL required (needs real Postgres)"
)


# --- Org creation on signup ---------------------------------------------------


def test_account_org_helper_wires_everything(monkeypatch):
    """_create_account_org must make the org, attach the store, and grant manager."""
    from routers import business

    calls = {}
    monkeypatch.setattr(
        business.database, "db_org_create", lambda name: {"id": "org-1", "name": name}
    )
    monkeypatch.setattr(
        business.database, "db_org_update_subscription",
        lambda oid, **kw: calls.setdefault("plan", kw.get("plan")),
    )
    monkeypatch.setattr(
        business.database, "db_org_attach_tenant",
        lambda tid, oid: calls.setdefault("attached", (tid, oid)),
    )
    monkeypatch.setattr(
        business.database, "db_org_member_add",
        lambda uid, oid, role: calls.setdefault("member", (uid, oid, role)),
    )
    org_id = business._create_account_org("user_1", "Acme Salon", {"id": "t-1"}, "growth")
    assert org_id == "org-1"
    assert calls["attached"] == ("t-1", "org-1")
    # Their own account — they manage it, not merely view it.
    assert calls["member"] == ("user_1", "org-1", "manager")
    assert calls["plan"] == "growth"


def test_signup_survives_org_creation_failure(monkeypatch):
    """A store that couldn't be wrapped in an org is still usable — never block signup."""
    from routers import business

    monkeypatch.setattr(business.database, "db_org_create", lambda name: None)
    assert business._create_account_org("user_1", "Acme", {"id": "t-1"}, "starter") is None


# --- Single-store resolution --------------------------------------------------


@_DB
def test_one_store_owner_lands_in_their_store_without_picking():
    """The promise: a solo owner never sees a store list."""
    database.init_db()
    org = database.db_org_create("Solo Salon")
    t = database.db_tenant_create_pending("solo-1", "Solo Salon", "pro", "salon_chair")
    database.db_org_attach_tenant(t["id"], org["id"])
    database.db_org_member_add("user_solo", org["id"], "manager")

    stores = database.db_org_stores_for_user("user_solo")
    assert len(stores) == 1
    assert stores[0]["client_id"] == "solo-1"


@_DB
def test_multi_store_owner_gets_the_list():
    """With more than one store there's a real choice to make, so no auto-resolve."""
    database.init_db()
    org = database.db_org_create("Two Locations")
    for i in range(2):
        t = database.db_tenant_create_pending(f"multi-{i}", f"Shop {i}", "pro", "salon_chair")
        database.db_org_attach_tenant(t["id"], org["id"])
    database.db_org_member_add("user_multi", org["id"], "manager")

    assert len(database.db_org_stores_for_user("user_multi")) == 2


@_DB
def test_adding_a_second_store_needs_no_migration():
    """The whole point of org-first: growing from one location to two is just an insert."""
    database.init_db()
    org = database.db_org_create("Growing")
    first = database.db_tenant_create_pending("grow-1", "First", "pro", "salon_chair")
    database.db_org_attach_tenant(first["id"], org["id"])
    database.db_org_member_add("user_grow", org["id"], "manager")
    assert database.db_org_store_count(org["id"]) == 1

    second = database.db_tenant_create_pending("grow-2", "Second", "pro", "salon_chair")
    database.db_org_attach_tenant(second["id"], org["id"])

    assert database.db_org_store_count(org["id"]) == 2
    assert {s["client_id"] for s in database.db_org_stores_for_user("user_grow")} == {
        "grow-1", "grow-2"
    }


@_DB
def test_store_manager_stays_scoped_to_their_own_store():
    """An invited store manager must not gain sight of the group's other stores."""
    database.init_db()
    org = database.db_org_create("Group")
    a = database.db_tenant_create_pending("scoped-a", "A", "pro", "salon_chair")
    b = database.db_tenant_create_pending("scoped-b", "B", "pro", "salon_chair")
    for t in (a, b):
        database.db_org_attach_tenant(t["id"], org["id"])
    # Store-level manager: a tenant member, NOT an org member.
    database.db_tenant_member_set_single("user_store_mgr", a["id"])

    assert database.db_org_stores_for_user("user_store_mgr") == []
    assert database.db_org_store_for_user("user_store_mgr", "scoped-b") is None
    own = database.db_tenant_get_for_user("user_store_mgr")
    assert own and own["client_id"] == "scoped-a"


# --- Billing flows through the org -------------------------------------------


@_DB
def test_store_is_live_on_its_orgs_subscription(monkeypatch):
    """One subscription on the account covers its store(s); the store never pays."""
    import runtime
    from subscription_access import get_tenant_subscription_state

    database.init_db()
    # monkeypatch, NOT a bare assignment: runtime.USE_DB is a module global, and
    # leaving it flipped leaks into every test that runs after this one.
    monkeypatch.setattr(runtime, "USE_DB", True)
    org = database.db_org_create("Paying Account")
    database.db_org_update_subscription(org["id"], subscription_status="active", plan="pro")
    t = database.db_tenant_create_pending("paid-store", "Store", "pro", "salon_chair")
    database.db_org_attach_tenant(t["id"], org["id"])

    fresh = database.db_tenant_get_by_id(t["id"])
    assert fresh["subscription_status"] == "incomplete"  # never had its own checkout
    state = get_tenant_subscription_state(fresh)
    assert state["can_use_app"] is True
    assert state["billing_source"] == "org"


@_DB
def test_inviting_a_store_manager_does_not_lock_out_the_owner():
    """Handing a store to a manager must not cost the owner their access.

    Accepting a store invite makes that person the SOLE tenant_member (it displaces
    whoever was there — including the owner, who became a member of their first store
    at signup). The owner keeps access purely through org membership, so this is the
    test that protects that dependency.
    """
    database.init_db()
    org = database.db_org_create("Owner Account")
    store = database.db_tenant_create_pending("handoff", "Store", "pro", "salon_chair")
    database.db_org_attach_tenant(store["id"], org["id"])
    database.db_org_member_add("user_owner", org["id"], "manager")
    database.db_tenant_member_set_single("user_owner", store["id"])  # as signup does

    # The owner hands the store to a manager; accepting the invite displaces them.
    database.db_tenant_member_set_single("user_store_mgr", store["id"])
    assert database.db_tenant_get_members(store["id"]) == ["user_store_mgr"]
    assert database.db_tenant_get_for_user("user_owner") is None  # no longer a member

    # ...but the owner still reaches it through the org — this is what saves them.
    still_theirs = database.db_org_stores_for_user("user_owner")
    assert [s["client_id"] for s in still_theirs] == ["handoff"]
    assert database.db_org_store_for_user("user_owner", "handoff") is not None

    # And the store manager sees only their store, never the group.
    assert database.db_org_stores_for_user("user_store_mgr") == []


@_DB
def test_quantity_tracks_locations():
    """Billed per store: the count is what the subscription quantity follows."""
    database.init_db()
    org = database.db_org_create("Counting")
    assert database.db_org_store_count(org["id"]) == 0
    for i in range(3):
        t = database.db_tenant_create_pending(f"qty-{i}", f"S{i}", "pro", "salon_chair")
        database.db_org_attach_tenant(t["id"], org["id"])
    assert database.db_org_store_count(org["id"]) == 3
