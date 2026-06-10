"""baseline: current production schema

Snapshot of the schema as built by database.init_db() at the time Alembic was
adopted. The ALTER-added columns that init_db() applied incrementally
(tenants subscription/billing columns, call_log recording columns,
appointments staff_id/reminder/decline columns, booked_slots.staff_id) are
folded directly into the CREATE TABLE statements here, so a database built
from this migration matches a fully-migrated production database.

Every statement is IF NOT EXISTS, so applying this against a database that
already has the schema is a harmless no-op. Existing databases should instead
be marked with `alembic stamp 0001_baseline` (see docs/MIGRATIONS.md) so this
DDL is never re-run against live data.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-10
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


# Tables in dependency order (tenants before its children). Each entry is the
# full CREATE TABLE IF NOT EXISTS, with previously-ALTERed columns folded in.
_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS appointments (
        id SERIAL PRIMARY KEY,
        client_id TEXT NOT NULL DEFAULT 'default',
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        date TEXT NOT NULL,
        time TEXT,
        reason TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        source TEXT DEFAULT 'manual',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        reminder_sent_at TIMESTAMPTZ,
        staff_id TEXT,
        owner_decline_reason TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        client_id TEXT NOT NULL DEFAULT 'default',
        caller_name TEXT,
        caller_phone TEXT,
        message TEXT,
        urgency TEXT DEFAULT 'normal',
        status TEXT DEFAULT 'unread',
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS call_log (
        id SERIAL PRIMARY KEY,
        client_id TEXT NOT NULL DEFAULT 'default',
        call_sid TEXT UNIQUE NOT NULL,
        from_number TEXT,
        to_number TEXT,
        start_iso TEXT,
        end_iso TEXT,
        outcome TEXT,
        duration_sec INTEGER,
        category TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        recording_sid TEXT,
        recording_url TEXT,
        recording_duration_sec INTEGER,
        recording_status TEXT,
        call_summary TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS caller_memory (
        phone TEXT NOT NULL,
        client_id TEXT NOT NULL DEFAULT 'default',
        name TEXT,
        call_count INTEGER DEFAULT 0,
        last_call_iso TEXT,
        last_reason TEXT,
        data JSONB,
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (phone, client_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS booked_slots (
        id SERIAL PRIMARY KEY,
        client_id TEXT NOT NULL DEFAULT 'default',
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        appointment_id INTEGER NOT NULL,
        duration_minutes INTEGER DEFAULT 30,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        staff_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tenants (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        client_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        twilio_phone_number TEXT NOT NULL,
        plan TEXT NOT NULL DEFAULT 'starter',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        trial_ends_at TIMESTAMPTZ,
        subscription_status TEXT,
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        billing_exempt_until TIMESTAMPTZ,
        business_vertical TEXT,
        billing_period_anchor_at TIMESTAMPTZ,
        business_config JSONB
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tenant_members (
        clerk_user_id TEXT NOT NULL,
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        role TEXT NOT NULL DEFAULT 'member',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (clerk_user_id, tenant_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tenant_invites (
        email TEXT PRIMARY KEY,
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sms_sessions (
        phone TEXT NOT NULL,
        client_id TEXT NOT NULL,
        messages JSONB DEFAULT '[]',
        appointment_id INT,
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (phone, client_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sms_opt_out (
        phone TEXT NOT NULL,
        client_id TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (phone, client_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id BIGSERIAL PRIMARY KEY,
        occurred_at TIMESTAMPTZ DEFAULT NOW(),
        actor_type TEXT NOT NULL,
        actor_id TEXT,
        action TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        client_id TEXT,
        details JSONB,
        ip TEXT,
        request_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tenant_removed_archive (
        id BIGSERIAL PRIMARY KEY,
        archived_at TIMESTAMPTZ DEFAULT NOW(),
        former_tenant_id UUID NOT NULL,
        client_id TEXT NOT NULL,
        actor_clerk_id TEXT,
        bundle JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS legal_holds (
        id BIGSERIAL PRIMARY KEY,
        client_id TEXT NOT NULL,
        reason TEXT,
        hold_until TIMESTAMPTZ,
        created_by TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(client_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_exports (
        id BIGSERIAL PRIMARY KEY,
        export_key TEXT NOT NULL UNIQUE,
        destination_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tenant_usage (
        id SERIAL PRIMARY KEY,
        client_id TEXT NOT NULL,
        month TEXT NOT NULL CHECK (month ~ '^\\d{4}-\\d{2}$'),
        voice_minutes INTEGER NOT NULL DEFAULT 0 CHECK (voice_minutes >= 0),
        sms_count INTEGER NOT NULL DEFAULT 0 CHECK (sms_count >= 0),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(client_id, month)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS leads (
        id SERIAL PRIMARY KEY,
        client_id TEXT NOT NULL,
        name TEXT,
        phone TEXT NOT NULL,
        reason TEXT,
        source TEXT CHECK (source IN ('call', 'sms')),
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sms_automations (
        id SERIAL PRIMARY KEY,
        client_id TEXT NOT NULL,
        trigger TEXT NOT NULL CHECK (trigger IN ('after_inquiry', 'post_call')),
        template TEXT NOT NULL,
        enabled BOOLEAN DEFAULT true,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS overage_processed (
        client_id TEXT NOT NULL,
        month TEXT NOT NULL CHECK (month ~ '^\\d{4}-\\d{2}$'),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (client_id, month)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversational_sms_period_usage (
        client_id TEXT NOT NULL,
        billing_period_key TEXT NOT NULL,
        session_count INTEGER NOT NULL DEFAULT 0 CHECK (session_count >= 0),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (client_id, billing_period_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversational_sms_session_keys (
        client_id TEXT NOT NULL,
        billing_period_key TEXT NOT NULL,
        phone_normalized TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (client_id, billing_period_key, phone_normalized)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cron_runs (
        id SERIAL PRIMARY KEY,
        job_name TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMPTZ,
        status TEXT NOT NULL DEFAULT 'running',
        summary JSONB
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provisioning_jobs (
        id TEXT PRIMARY KEY,
        created_by TEXT,
        total INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provisioning_tasks (
        id SERIAL PRIMARY KEY,
        job_id TEXT NOT NULL,
        client_id TEXT NOT NULL,
        name TEXT,
        email TEXT,
        area_code TEXT,
        plan TEXT NOT NULL DEFAULT 'free',
        status TEXT NOT NULL DEFAULT 'pending',
        phone_e164 TEXT,
        steps_done JSONB NOT NULL DEFAULT '[]'::jsonb,
        error TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]

# Indexes (after all tables exist).
_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_invites_one_email_per_tenant ON tenant_invites (tenant_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_members_one_per_tenant ON tenant_members (tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_tenants_twilio_phone ON tenants(twilio_phone_number)",
    "CREATE INDEX IF NOT EXISTS idx_sms_opt_out_client ON sms_opt_out(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_client_occurred ON audit_events(client_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_action_occurred ON audit_events(action, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_tenant_removed_archive_client ON tenant_removed_archive(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_tenant_removed_archive_time ON tenant_removed_archive(archived_at)",
    "CREATE INDEX IF NOT EXISTS idx_legal_holds_client ON legal_holds(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_backup_exports_created ON backup_exports(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_tenant_usage_client_month ON tenant_usage(client_id, month)",
    "CREATE INDEX IF NOT EXISTS idx_leads_client_created ON leads(client_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sms_automations_client ON sms_automations(client_id)",
    "CREATE INDEX IF NOT EXISTS idx_conv_sms_sessions_client_period ON conversational_sms_session_keys(client_id, billing_period_key)",
    "CREATE INDEX IF NOT EXISTS idx_cron_runs_job_finished ON cron_runs(job_name, finished_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_provisioning_tasks_job ON provisioning_tasks(job_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_appointments_status_date ON appointments(client_id, status)",
]


def upgrade() -> None:
    for ddl in _TABLES:
        op.execute(ddl)
    for ddl in _INDEXES:
        op.execute(ddl)


def downgrade() -> None:
    # Drop in reverse dependency order. CASCADE clears the FK-bound children
    # (tenant_members, tenant_invites) and any dependent indexes.
    for table in reversed([
        "appointments", "messages", "call_log", "caller_memory", "booked_slots",
        "tenants", "tenant_members", "tenant_invites", "sms_sessions",
        "sms_opt_out", "audit_events", "tenant_removed_archive", "legal_holds",
        "backup_exports", "tenant_usage", "leads", "sms_automations",
        "overage_processed", "conversational_sms_period_usage",
        "conversational_sms_session_keys", "cron_runs", "provisioning_jobs",
        "provisioning_tasks",
    ]):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
