"""org-level billing — one subscription covering N stores

A franchise buys once for the whole group, not once per shop. The org carries the
Stripe customer/subscription and the stores inherit access from it: a store whose
org has an active subscription is live even though the store itself never saw a
card (its own subscription_status stays 'incomplete' forever).

Columns mirror the tenant billing columns on purpose, so subscription_access can
evaluate an org with the same rules it already applies to a tenant.

Mirrors the same additive changes applied idempotently in database.init_db().

Revision ID: 0010_org_billing
Revises: 0009_orgs_multi_store
Create Date: 2026-07-17
"""
from alembic import op

revision = "0010_org_billing"
down_revision = "0009_orgs_multi_store"
branch_labels = None
depends_on = None


_COLUMNS = [
    ("plan", "TEXT NOT NULL DEFAULT 'pro'"),
    ("subscription_status", "TEXT"),
    ("stripe_customer_id", "TEXT"),
    ("stripe_subscription_id", "TEXT"),
    ("trial_ends_at", "TIMESTAMPTZ"),
    ("billing_exempt_until", "TIMESTAMPTZ"),
]


def upgrade() -> None:
    for col, typ in _COLUMNS:
        op.execute(f"ALTER TABLE orgs ADD COLUMN IF NOT EXISTS {col} {typ}")


def downgrade() -> None:
    for col, _ in _COLUMNS:
        op.execute(f"ALTER TABLE orgs DROP COLUMN IF EXISTS {col}")
