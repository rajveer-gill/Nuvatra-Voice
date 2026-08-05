"""Scope an org membership to a single store.

A store manager invited by a regional manager should get that one store and nothing
else. Until now they were made a tenant_member instead, which runs through
db_tenant_member_assign_owner — "make this user the sole owner of the tenant" — so
inviting someone who already had an account deleted every other membership they had,
and every other member of that store. Non-destructive alternatives don't survive
either, because db_tenant_get_for_user collapses multi-membership on read.

Org membership is the model that already fits: it is explicitly exempt from all that
collapsing. It just needed to be narrowable from "the whole group" to "one store".

NULL tenant_id = the whole org (a regional manager). Set = that store only.

Revision ID: 0012_org_member_store_scope
Revises: 0011_org_invites
"""

from alembic import op

revision = "0012_org_member_store_scope"
down_revision = "0011_org_invites"
branch_labels = None
depends_on = None


def upgrade():
    # ON DELETE CASCADE: deleting a store should take its manager's access with it,
    # not leave a membership pointing at nothing that resolves to the whole org.
    op.execute(
        "ALTER TABLE org_members ADD COLUMN IF NOT EXISTS tenant_id UUID "
        "REFERENCES tenants(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE org_invites ADD COLUMN IF NOT EXISTS tenant_id UUID "
        "REFERENCES tenants(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_org_members_tenant ON org_members(tenant_id)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_org_members_tenant")
    op.execute("ALTER TABLE org_members DROP COLUMN IF EXISTS tenant_id")
    op.execute("ALTER TABLE org_invites DROP COLUMN IF EXISTS tenant_id")
