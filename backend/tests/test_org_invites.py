"""Org invites: invite by email before sign-up, consume at first login, revoke.

These are the DB-level guarantees. The Clerk send and the get_org_me consumption
trigger are thin wrappers around db_org_invites_consume_for_emails, which is what's
exercised here.
"""

from __future__ import annotations

import os

import pytest

import database

_DB = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL required (needs real Postgres)"
)


@_DB
def test_invite_is_consumed_on_matching_email():
    database.init_db()
    org = database.db_org_create("Region")
    assert database.db_org_invite_upsert("Manager@Co.com", org["id"], "manager")

    # First sign-in: Clerk reports this verified email (note the different casing).
    joined = database.db_org_invites_consume_for_emails("user_new", ["manager@co.com"])
    assert len(joined) == 1
    assert joined[0]["role"] == "manager"

    # They're now a real member, and the pending invite is gone.
    mems = database.db_org_memberships("user_new")
    assert [m["org_id"] for m in mems] == [org["id"]]
    assert database.db_org_invites_for_org(org["id"]) == []


@_DB
def test_unmatched_email_leaves_the_invite_pending():
    database.init_db()
    org = database.db_org_create("Region")
    database.db_org_invite_upsert("wanted@co.com", org["id"], "viewer")

    # A different user signs in — no match, invite untouched.
    assert database.db_org_invites_consume_for_emails("user_other", ["someone@else.com"]) == []
    assert database.db_org_memberships("user_other") == []
    assert len(database.db_org_invites_for_org(org["id"])) == 1


@_DB
def test_consuming_twice_is_a_no_op():
    """Two concurrent first-load requests must not double-add or error."""
    database.init_db()
    org = database.db_org_create("Region")
    database.db_org_invite_upsert("m@co.com", org["id"], "manager")

    first = database.db_org_invites_consume_for_emails("user_1", ["m@co.com"])
    second = database.db_org_invites_consume_for_emails("user_1", ["m@co.com"])
    assert len(first) == 1
    assert second == []  # nothing left to claim
    assert len(database.db_org_memberships("user_1")) == 1


@_DB
def test_one_email_can_be_invited_to_several_groups():
    database.init_db()
    a = database.db_org_create("Region A")
    b = database.db_org_create("Region B")
    database.db_org_invite_upsert("boss@co.com", a["id"], "manager")
    database.db_org_invite_upsert("boss@co.com", b["id"], "viewer")

    joined = database.db_org_invites_consume_for_emails("user_boss", ["boss@co.com"])
    assert len(joined) == 2
    roles = {j["org_id"]: j["role"] for j in joined}
    assert roles[a["id"]] == "manager"
    assert roles[b["id"]] == "viewer"


@_DB
def test_revoking_a_pending_invite():
    database.init_db()
    org = database.db_org_create("Region")
    database.db_org_invite_upsert("gone@co.com", org["id"], "viewer")
    assert database.db_org_invite_delete("gone@co.com", org["id"]) is True
    # Now signing in gains nothing.
    assert database.db_org_invites_consume_for_emails("user_x", ["gone@co.com"]) == []
    assert database.db_org_memberships("user_x") == []


@_DB
def test_invite_upsert_rerole_and_role_floor():
    database.init_db()
    org = database.db_org_create("Region")
    database.db_org_invite_upsert("p@co.com", org["id"], "viewer")
    database.db_org_invite_upsert("p@co.com", org["id"], "manager")  # re-role, not duplicate
    invites = database.db_org_invites_for_org(org["id"])
    assert len(invites) == 1 and invites[0]["role"] == "manager"

    # An unknown role must floor to viewer, never grant more than asked.
    database.db_org_invite_upsert("q@co.com", org["id"], "wizard")
    q = [i for i in database.db_org_invites_for_org(org["id"]) if i["email"] == "q@co.com"][0]
    assert q["role"] == "viewer"


@_DB
def test_already_a_member_still_clears_the_invite():
    """A stray invite for someone already in the org must not linger forever."""
    database.init_db()
    org = database.db_org_create("Region")
    database.db_org_member_add("user_dup", org["id"], "manager")
    database.db_org_invite_upsert("dup@co.com", org["id"], "viewer")

    database.db_org_invites_consume_for_emails("user_dup", ["dup@co.com"])
    assert database.db_org_invites_for_org(org["id"]) == []
    # Their existing manager role must survive — a stray viewer invite can't demote them.
    mems = database.db_org_memberships("user_dup")
    assert mems[0]["role"] == "manager"


@_DB
def test_invites_deleted_with_their_org():
    """ON DELETE CASCADE: dropping an org clears its pending invites."""
    database.init_db()
    org = database.db_org_create("Region")
    database.db_org_invite_upsert("x@co.com", org["id"], "viewer")
    # Delete via raw SQL (no helper needed); the cascade should take the invite.
    conn = database._get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM orgs WHERE id = %s::uuid", (org["id"],))
    conn.commit()
    cur.close()
    assert database.db_org_invites_for_org(org["id"]) == []
