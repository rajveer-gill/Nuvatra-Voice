"""account_paused + twilio_number_sid on tenants, usage_alert_sent table

Adds:
- tenants.account_paused — admin manual kill-switch; flows through the
  subscription-access gate so a paused tenant's voice/SMS webhooks decline.
- tenants.twilio_number_sid — store the Twilio incoming-number SID (PNxxxx) so
  numbers can be released reliably on cancellation/deletion without a lookup.
- usage_alert_sent — dedup guard so a usage-cap alert fires at most once per
  tenant per month.

Mirrors the same additive changes applied idempotently in database.init_db().

Revision ID: 0004_account_paused_twilio_sid_usage_alert
Revises: 0003_tenant_phone_nullable
Create Date: 2026-06-13
"""
from alembic import op

revision = "0004_account_paused_twilio_sid_usage_alert"
down_revision = "0003_tenant_phone_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS account_paused BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS twilio_number_sid TEXT")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_alert_sent (
            client_id TEXT NOT NULL,
            month TEXT NOT NULL CHECK (month ~ '^\\d{4}-\\d{2}$'),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (client_id, month)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_alert_sent")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS twilio_number_sid")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS account_paused")
