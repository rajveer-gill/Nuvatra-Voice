"""Referral program: codes, redemptions, commission ledger, signup anti-abuse ledger

Adds:
- signup_payment_methods — global ledger of card fingerprint + email per completed
  signup (referred or not), so a card/email reused across ANY prior signup is caught.
- referral_codes — admin-issued, shareable codes tied to a referrer.
- referral_redemptions — one per tenant; tracks grant/flag/convert + snapshots.
- referral_commissions — payout ledger ($200 bounty + 25% MRR), idempotent per
  (redemption_id, kind, period_key), with snapshots so payout history survives edits.

Mirrors the same additive DDL applied idempotently in database.init_db().

Revision ID: 0005_referral_program
Revises: 0004_account_paused_twilio_sid_usage_alert
Create Date: 2026-06-13
"""
from alembic import op

revision = "0005_referral_program"
down_revision = "0004_account_paused_twilio_sid_usage_alert"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS signup_payment_methods (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT,
            card_fingerprint TEXT,
            signup_email TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_signup_pm_fingerprint ON signup_payment_methods(card_fingerprint)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_signup_pm_email ON signup_payment_methods(signup_email)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_codes (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            referrer_name TEXT NOT NULL,
            referrer_contact TEXT,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_referral_codes_active ON referral_codes(active)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_redemptions (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL UNIQUE,
            referral_code_id BIGINT REFERENCES referral_codes(id) ON DELETE SET NULL,
            code_snapshot TEXT NOT NULL,
            referrer_name_snapshot TEXT NOT NULL,
            plan_at_signup TEXT,
            card_fingerprint TEXT,
            signup_email TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','granted','flagged','converted')),
            free_month_granted BOOLEAN NOT NULL DEFAULT FALSE,
            flagged_reason TEXT,
            stripe_subscription_id TEXT,
            first_paid_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_referral_redemptions_sub ON referral_redemptions(stripe_subscription_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_referral_redemptions_fp ON referral_redemptions(card_fingerprint)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_referral_redemptions_email ON referral_redemptions(signup_email)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_commissions (
            id BIGSERIAL PRIMARY KEY,
            redemption_id BIGINT REFERENCES referral_redemptions(id) ON DELETE SET NULL,
            kind TEXT NOT NULL CHECK (kind IN ('signup_bounty','mrr')),
            period_key TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
            plan_snapshot TEXT,
            code_snapshot TEXT NOT NULL,
            referrer_name_snapshot TEXT NOT NULL,
            paid BOOLEAN NOT NULL DEFAULT FALSE,
            paid_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (redemption_id, kind, period_key)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_referral_commissions_unpaid ON referral_commissions(paid)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_referral_commissions_redemption ON referral_commissions(redemption_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS referral_commissions")
    op.execute("DROP TABLE IF EXISTS referral_redemptions")
    op.execute("DROP TABLE IF EXISTS referral_codes")
    op.execute("DROP TABLE IF EXISTS signup_payment_methods")
