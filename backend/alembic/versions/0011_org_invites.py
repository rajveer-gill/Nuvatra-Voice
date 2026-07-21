"""org_invites — invite an org overseer/manager by email before they sign up

The admin panel could only add someone who already had a Nuvatra account, because
adding a member resolves an email to a Clerk user id. This mirrors tenant_invites:
a pending row keyed by email, consumed the first time that person signs in with a
matching verified email (see routers/org.get_org_me).

Composite PK (email, org_id) so one person can be invited to several groups — unlike
tenant_invites, which is one-per-tenant.

Mirrors the same additive change applied idempotently in database.init_db().

Revision ID: 0011_org_invites
Revises: 0010_org_billing
Create Date: 2026-07-17
"""
from alembic import op

revision = "0011_org_invites"
down_revision = "0010_org_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS org_invites (
            email TEXT NOT NULL,
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (email, org_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_invites_email ON org_invites(email)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_org_invites_email")
    op.execute("DROP TABLE IF EXISTS org_invites")
