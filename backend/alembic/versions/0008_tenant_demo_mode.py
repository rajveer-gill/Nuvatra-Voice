"""tenants.demo_mode — card-free demo accounts

Adds tenants.demo_mode, the flag for a prospect exploring a seeded dashboard
before paying. A demo tenant has NO twilio_phone_number (so no call can route
to it) and a short billing_exempt_until (so can_use_app is true at pro tier).

The flag exists so the sample-data purge on activation has an explicit gate:
purging is destructive and must never fire against a tenant whose data could
be real. demo_mode is cleared in the same transaction as the purge, so it can
only ever fire once per tenant.

Mirrors the same additive change applied idempotently in database.init_db().

Revision ID: 0008_tenant_demo_mode
Revises: 0007_booked_slots_unique
Create Date: 2026-07-16
"""
from alembic import op

revision = "0008_tenant_demo_mode"
down_revision = "0007_booked_slots_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS demo_mode BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS demo_mode")
