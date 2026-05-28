"""One Clerk user per tenant; one tenant membership per user."""
import os
import uuid

import pytest

from database import (
    db_tenant_create,
    db_tenant_member_assign_owner,
    db_tenant_membership_tenant_ids,
    db_tenant_get_members,
    db_tenant_invite_upsert,
    db_tenant_delete,
    init_db,
    _get_conn,
)

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")


def _create_test_tenant(slug: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    client_id = f"{slug}-{suffix}"
    phone = f"+1555{suffix[:7]}"
    row = db_tenant_create(client_id, f"Test {slug}", phone, "free")
    assert row is not None
    return str(row["id"])


def test_assign_owner_displaces_prior_member():
    init_db()
    tenant_a = _create_test_tenant("exclusive-a")
    tenant_b = _create_test_tenant("exclusive-b")
    user_old = f"clerk_user_old_{uuid.uuid4().hex[:8]}"
    user_new = f"clerk_user_new_{uuid.uuid4().hex[:8]}"

    try:
        displaced = db_tenant_member_assign_owner(user_old, tenant_a)
        assert displaced == []

        displaced = db_tenant_member_assign_owner(user_new, tenant_a)
        assert user_old in displaced
        assert db_tenant_get_members(tenant_a) == [user_new]
        assert db_tenant_membership_tenant_ids(user_old) == []
        assert db_tenant_membership_tenant_ids(user_new) == [tenant_a]

        db_tenant_member_assign_owner(user_old, tenant_b)
        assert db_tenant_membership_tenant_ids(user_new) == [tenant_a]
        assert db_tenant_membership_tenant_ids(user_old) == [tenant_b]
    finally:
        db_tenant_delete(tenant_a)
        db_tenant_delete(tenant_b)


def test_invite_upsert_replaces_other_emails_for_same_tenant():
    init_db()
    tenant_id = _create_test_tenant("exclusive-invite")
    try:
        db_tenant_invite_upsert("first@example.com", tenant_id)
        db_tenant_invite_upsert("second@example.com", tenant_id)

        conn = _get_conn()
        assert conn is not None
        cur = conn.cursor()
        cur.execute("SELECT email FROM tenant_invites WHERE tenant_id = %s::uuid", (tenant_id,))
        emails = {r[0] for r in cur.fetchall()}
        cur.close()
        assert emails == {"second@example.com"}
    finally:
        db_tenant_delete(tenant_id)
