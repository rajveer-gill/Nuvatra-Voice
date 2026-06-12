"""tenants.twilio_phone_number nullable (self-serve pending tenants)

Self-serve signup creates a tenant before its number is provisioned — the number
is purchased when Stripe checkout completes — so the column must allow NULL.
Mirrors the same DROP NOT NULL applied idempotently in database.init_db().

Revision ID: 0003_tenant_phone_nullable
Revises: 0002_sms_consent_and_confirmation_flag
Create Date: 2026-06-11
"""
from alembic import op

revision = "0003_tenant_phone_nullable"
down_revision = "0002_sms_consent_and_confirmation_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ALTER COLUMN twilio_phone_number DROP NOT NULL")


def downgrade() -> None:
    # Re-imposing NOT NULL would fail if any pending tenants have a NULL number;
    # blank them first is unsafe, so this is a best-effort restore.
    op.execute("ALTER TABLE tenants ALTER COLUMN twilio_phone_number SET NOT NULL")
