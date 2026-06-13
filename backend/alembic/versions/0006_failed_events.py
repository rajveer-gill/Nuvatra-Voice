"""failed_events incident/dead-letter log

Swallowed failures (Stripe/Twilio webhook handler errors, cron failures, background
task failures) are recorded here so they're visible in the admin panel and retryable,
instead of disappearing into application logs.

Mirrors the same additive DDL applied idempotently in database.init_db().

Revision ID: 0006_failed_events
Revises: 0005_referral_program
Create Date: 2026-06-13
"""
from alembic import op

revision = "0006_failed_events"
down_revision = "0005_referral_program"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS failed_events (
            id BIGSERIAL PRIMARY KEY,
            source TEXT NOT NULL,
            event_type TEXT,
            ref TEXT,
            error TEXT,
            payload JSONB,
            resolved BOOLEAN NOT NULL DEFAULT FALSE,
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_failed_events_unresolved ON failed_events(resolved, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS failed_events")
