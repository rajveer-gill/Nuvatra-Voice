"""Per-org price overrides, so a partner rate can be per store.

"$50 off each store" cannot be a Stripe coupon. amount_off comes off the invoice,
and an org is one subscription with quantity = store count, so a fixed discount
applies once no matter whether that is 2 stores or 43. A percentage is per-store but
breaks the moment the plan changes: 33% is $50 off Starter, $83 off Growth, $133 off
Pro.

A discounted price is per-store by construction — quantity multiplies the unit price
— and stays exactly $50 across plans. NULL means the standard env-configured price,
so every other customer is unaffected.

Revision ID: 0013_org_price_overrides
Revises: 0012_org_member_store_scope
"""

from alembic import op

revision = "0013_org_price_overrides"
down_revision = "0012_org_member_store_scope"
branch_labels = None
depends_on = None


def upgrade():
    # JSONB keyed by plan ("starter"/"growth"/"pro") so a new plan needs no migration.
    op.execute("ALTER TABLE orgs ADD COLUMN IF NOT EXISTS price_overrides JSONB")


def downgrade():
    op.execute("ALTER TABLE orgs DROP COLUMN IF EXISTS price_overrides")
