"""sms_consent ledger + appointments.confirmation_sms_failed

Two additive changes:

1. ``sms_consent`` — an append-only consent ledger. One row per consent event
   captured at a real entry point (inbound call, inbound SMS, START opt-in,
   voice booking). This is the provable opt-in trail that complements the
   existing opt-OUT table (``sms_opt_out``), so a business can demonstrate
   when/how a number consented to service texts (TCPA / A2P 10DLC).

2. ``appointments.confirmation_sms_failed`` — a flag set when a dashboard
   accept/reject/cancel could not deliver its confirmation text, so the
   dashboard can surface "text didn't send — call the customer" instead of
   silently reporting success.

Both are IF NOT EXISTS / additive, so re-applying is a no-op.

Revision ID: 0002_sms_consent_and_confirmation_flag
Revises: 0001_baseline
Create Date: 2026-06-10
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_sms_consent_and_confirmation_flag"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


_CONSENT_TABLE = """
    CREATE TABLE IF NOT EXISTS sms_consent (
        id BIGSERIAL PRIMARY KEY,
        phone TEXT NOT NULL,
        client_id TEXT NOT NULL DEFAULT 'default',
        consent_type TEXT NOT NULL DEFAULT 'service',
        source TEXT NOT NULL,
        detail JSONB,
        ip TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
"""

_CONSENT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_sms_consent_phone_client ON sms_consent(phone, client_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sms_consent_client_created ON sms_consent(client_id, created_at DESC)",
]

_APPOINTMENT_FLAG = (
    "ALTER TABLE appointments "
    "ADD COLUMN IF NOT EXISTS confirmation_sms_failed BOOLEAN NOT NULL DEFAULT false"
)


def upgrade() -> None:
    op.execute(_CONSENT_TABLE)
    for ddl in _CONSENT_INDEXES:
        op.execute(ddl)
    op.execute(_APPOINTMENT_FLAG)


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS confirmation_sms_failed")
    op.execute("DROP TABLE IF EXISTS sms_consent CASCADE")
