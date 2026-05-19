"""Pending invite email → tenant link (multi-tenant onboarding)."""
import os

import pytest

from database import (
    db_tenant_invite_upsert,
    db_tenant_invite_consume,
    db_tenant_invite_delete,
    _normalize_invite_email,
    init_db,
)

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")


def test_normalize_invite_email():
    assert _normalize_invite_email("  User@Example.COM ") == "user@example.com"


def test_invite_upsert_consume_delete():
    init_db()
    tid = "00000000-0000-0000-0000-000000000099"
    email = "invite-test@example.com"
    db_tenant_invite_delete(email)
    assert db_tenant_invite_upsert(email, tid) is True
    assert db_tenant_invite_consume("INVITE-TEST@example.com") == tid
    assert db_tenant_invite_consume(email) is None
