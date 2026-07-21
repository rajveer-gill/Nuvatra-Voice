"""orgs + org_members + tenants.org_id — multi-store oversight accounts

A franchise/group wants one login that can watch several stores' dashboards. The
existing model is deliberately one user <-> one tenant, enforced by deletion in
db_tenant_member_assign_owner and by the idx_tenant_members_one_per_tenant unique
index. Rather than dismantle that (it protects the normal owner case), oversight
is modelled alongside it:

- orgs           — a group of stores (e.g. a franchisee's region)
- org_members    — who can oversee that group, and at what role
- tenants.org_id — which group a store belongs to (NULL = independent, the default)

An org member is NOT a tenant_member of any store, so none of the single-tenant
enforcement changes and existing owners are unaffected. Store access is resolved
by joining org_members to tenants on org_id, which validates membership in the
same query that fetches the store.

Mirrors the same additive changes applied idempotently in database.init_db().

Revision ID: 0009_orgs_multi_store
Revises: 0008_tenant_demo_mode
Create Date: 2026-07-16
"""
from alembic import op

revision = "0009_orgs_multi_store"
down_revision = "0008_tenant_demo_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS orgs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS org_members (
            clerk_user_id TEXT NOT NULL,
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (clerk_user_id, org_id)
        )
        """
    )
    # NULL org_id = an independent store, which is every existing tenant.
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS org_id UUID "
        "REFERENCES orgs(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_tenants_org ON tenants(org_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_members_user ON org_members(clerk_user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_org_members_user")
    op.execute("DROP INDEX IF EXISTS idx_tenants_org")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS org_id")
    op.execute("DROP TABLE IF EXISTS org_members")
    op.execute("DROP TABLE IF EXISTS orgs")
