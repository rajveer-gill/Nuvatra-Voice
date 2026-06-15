"""Unique calendar hold per slot (concurrency: no double-booking)

Two simultaneous bookings could previously claim the same slot (check-then-reserve
race) and the delete-all + re-insert save could lose a concurrent hold. Add a unique
index on (client_id, date, time, COALESCE(staff_id,'')) so the DB rejects a double
hold; reserve_slot now does a single ON CONFLICT DO NOTHING insert and reports taken.

Dedupe existing rows (keep lowest id) before creating the index, or it would fail.

Mirrors the same additive DDL applied idempotently in database.init_db().

Revision ID: 0007_booked_slots_unique
Revises: 0006_failed_events
Create Date: 2026-06-15
"""
from alembic import op

revision = "0007_booked_slots_unique"
down_revision = "0006_failed_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE booked_slots ADD COLUMN IF NOT EXISTS staff_id TEXT")
    op.execute(
        """
        DELETE FROM booked_slots a USING booked_slots b
        WHERE a.id < b.id
          AND a.client_id = b.client_id AND a.date = b.date AND a.time = b.time
          AND COALESCE(a.staff_id, '') = COALESCE(b.staff_id, '')
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_booked_slots_unique "
        "ON booked_slots (client_id, date, time, (COALESCE(staff_id, '')))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_booked_slots_unique")
