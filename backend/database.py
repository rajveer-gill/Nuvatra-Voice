"""
PostgreSQL database layer for production. Used when DATABASE_URL is set.
Tables: appointments, messages, call_log, caller_memory, booked_slots, tenants, tenant_members
"""
import os
import json
import contextvars
from datetime import datetime
from typing import Optional, List, Tuple
from pathlib import Path

# Request-scoped client_id (set by auth middleware or webhook)
_request_client_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_client_id", default=None)

def set_request_client_id(client_id: Optional[str]) -> None:
    """Set the current request's client_id for all DB operations in this context."""
    if client_id is not None:
        _request_client_id.set(client_id)
    else:
        try:
            _request_client_id.set(None)
        except LookupError:
            pass

def clear_request_client_id() -> None:
    """Clear the request client_id context (e.g. after request completes)."""
    try:
        _request_client_id.reset(_request_client_id.get())
    except LookupError:
        pass

# Will be set on first use
_conn = None
_use_db = False

def _get_conn():
    global _conn, _use_db
    if not _use_db:
        return None
    if _conn is None or _conn.closed:
        import psycopg2
        url = os.getenv("DATABASE_URL")
        if not url:
            return None
        _conn = psycopg2.connect(url, connect_timeout=10)
    return _conn

def db_ping() -> bool:
    """Return True if DB is reachable (for health check)."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        return True
    except Exception:
        return False

def init_db() -> bool:
    """Initialize database: create tables if not exist. Returns True if DB is used."""
    global _use_db
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        import psycopg2
        print("[DB] Connecting to PostgreSQL...")
        conn = psycopg2.connect(url, connect_timeout=10)
        cur = conn.cursor()
        cur.execute("""
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
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
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
        """)
        cur.execute("""
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
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
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
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS booked_slots (
                id SERIAL PRIMARY KEY,
                client_id TEXT NOT NULL DEFAULT 'default',
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                appointment_id INTEGER NOT NULL,
                duration_minutes INTEGER DEFAULT 30,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                client_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                twilio_phone_number TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT 'starter',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Migration: add subscription/trial columns if missing (PostgreSQL 9.5+)
        for col, typ in [
            ("trial_ends_at", "TIMESTAMPTZ"),
            ("subscription_status", "TEXT"),
            ("stripe_customer_id", "TEXT"),
            ("stripe_subscription_id", "TEXT"),
            ("billing_exempt_until", "TIMESTAMPTZ"),
        ]:
            try:
                cur.execute(f"ALTER TABLE tenants ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception:
                pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tenant_members (
                clerk_user_id TEXT NOT NULL,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'member',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (clerk_user_id, tenant_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tenants_twilio_phone ON tenants(twilio_phone_number)")
        for col, typ in [
            ("recording_sid", "TEXT"),
            ("recording_url", "TEXT"),
            ("recording_duration_sec", "INTEGER"),
            ("recording_status", "TEXT"),
            ("call_summary", "TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE call_log ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception:
                pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sms_sessions (
                phone TEXT NOT NULL,
                client_id TEXT NOT NULL,
                messages JSONB DEFAULT '[]',
                appointment_id INT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (phone, client_id)
            )
        """)
        cur.execute("""
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
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_client_occurred ON audit_events(client_id, occurred_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_action_occurred ON audit_events(action, occurred_at)")
        # Plan tier tables
        cur.execute("""
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
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tenant_usage_client_month ON tenant_usage(client_id, month)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                client_id TEXT NOT NULL,
                name TEXT,
                phone TEXT NOT NULL,
                reason TEXT,
                source TEXT CHECK (source IN ('call', 'sms')),
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_client_created ON leads(client_id, created_at DESC)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sms_automations (
                id SERIAL PRIMARY KEY,
                client_id TEXT NOT NULL,
                trigger TEXT NOT NULL CHECK (trigger IN ('after_inquiry', 'post_call')),
                template TEXT NOT NULL,
                enabled BOOLEAN DEFAULT true,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sms_automations_client ON sms_automations(client_id)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS overage_processed (
                client_id TEXT NOT NULL,
                month TEXT NOT NULL CHECK (month ~ '^\\d{4}-\\d{2}$'),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (client_id, month)
            )
        """)
        try:
            cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ")
        except Exception:
            pass
        cur.execute("CREATE INDEX IF NOT EXISTS idx_appointments_status_date ON appointments(client_id, status)")
        conn.commit()
        cur.close()
        conn.close()
        _use_db = True
        print("[DB] PostgreSQL initialized successfully")
        return True
    except Exception as e:
        print(f"[DB] Failed to init PostgreSQL: {e}")
        return False

def _client_id() -> str:
    """Current request's client_id from context, or CLIENT_ID env, or 'default'."""
    ctx = _request_client_id.get(None)
    if ctx:
        return ctx
    return os.getenv("CLIENT_ID", "").strip() or "default"

def _normalize_e164(phone: str) -> str:
    """Convert to E.164 for Twilio lookup."""
    d = "".join(c for c in (phone or "") if c.isdigit())
    if len(d) == 10:
        return f"+1{d}"
    if len(d) == 11 and d.startswith("1"):
        return f"+{d}"
    return f"+{d}" if d else phone

# --- Tenants ---
def db_tenant_create(client_id: str, name: str, twilio_phone_number: str, plan: str = "free") -> Optional[dict]:
    """Create a tenant with 7-day trial. Returns tenant dict or None on conflict."""
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tenants (client_id, name, twilio_phone_number, plan, subscription_status, trial_ends_at)
            VALUES (%s, %s, %s, %s, 'trialing', NOW() + INTERVAL '7 days')
            ON CONFLICT (client_id) DO NOTHING
            RETURNING id, client_id, name, twilio_phone_number, plan, created_at,
                trial_ends_at, subscription_status, stripe_customer_id, stripe_subscription_id, billing_exempt_until
        """, (client_id, name, twilio_phone_number, plan))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            return None
        return _row_to_tenant(row)
    except Exception as e:
        print(f"[DB] Failed to create tenant: {e}")
        return None

def _row_to_tenant(row) -> dict:
    """Map tenant SELECT row (with subscription columns) to dict. Row has 11 cols from _tenant_select_cols."""
    base = {"id": str(row[0]), "client_id": row[1], "name": row[2], "twilio_phone_number": row[3], "plan": row[4]}
    base["created_at"] = row[5].isoformat() if len(row) > 5 and row[5] else None
    if len(row) >= 11:
        base["trial_ends_at"] = row[6].isoformat() if row[6] else None
        base["subscription_status"] = row[7] or "trialing"
        base["stripe_customer_id"] = row[8]
        base["stripe_subscription_id"] = row[9]
        base["billing_exempt_until"] = row[10].isoformat() if row[10] else None
    else:
        base["trial_ends_at"] = None
        base["subscription_status"] = "trialing"
        base["stripe_customer_id"] = None
        base["stripe_subscription_id"] = None
        base["billing_exempt_until"] = None
    return base

def _tenant_select_cols():
    return "id, client_id, name, twilio_phone_number, plan, created_at, trial_ends_at, subscription_status, stripe_customer_id, stripe_subscription_id, billing_exempt_until"

def db_tenant_get_by_phone(twilio_phone_number: str) -> Optional[dict]:
    """Look up tenant by Twilio phone number (E.164). Returns tenant or None."""
    conn = _get_conn()
    if not conn:
        return None
    cur = conn.cursor()
    normalized = _normalize_e164(twilio_phone_number or "")
    cur.execute(f"""
        SELECT {_tenant_select_cols()}
        FROM tenants WHERE twilio_phone_number IN (%s, %s)
        LIMIT 1
    """, (twilio_phone_number or "", normalized))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return _row_to_tenant(row)

def db_tenant_get_by_id(tenant_id: str) -> Optional[dict]:
    """Look up tenant by UUID."""
    conn = _get_conn()
    if not conn:
        return None
    cur = conn.cursor()
    cur.execute(f"SELECT {_tenant_select_cols()} FROM tenants WHERE id = %s", (tenant_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return _row_to_tenant(row)

def db_tenant_member_add(clerk_user_id: str, tenant_id: str) -> bool:
    """Add a member to a tenant. Returns True on success."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tenant_members (clerk_user_id, tenant_id)
            VALUES (%s, %s)
            ON CONFLICT (clerk_user_id, tenant_id) DO NOTHING
        """, (clerk_user_id, tenant_id))
        cur.close()
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Failed to add tenant member: {e}")
        return False

def db_tenant_get_for_user(clerk_user_id: str) -> Optional[dict]:
    """Get the tenant for a Clerk user (from tenant_members). Returns first tenant if multiple."""
    conn = _get_conn()
    if not conn:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT t.id, t.client_id, t.name, t.twilio_phone_number, t.plan, t.created_at,
               t.trial_ends_at, t.subscription_status, t.stripe_customer_id, t.stripe_subscription_id, t.billing_exempt_until
        FROM tenants t
        JOIN tenant_members m ON m.tenant_id = t.id
        WHERE m.clerk_user_id = %s
        LIMIT 1
    """, (clerk_user_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return _row_to_tenant(row)

def db_tenant_get_members(tenant_id: str) -> List[str]:
    """Get all clerk_user_ids for a tenant."""
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute("SELECT clerk_user_id FROM tenant_members WHERE tenant_id = %s", (tenant_id,))
    rows = cur.fetchall()
    cur.close()
    return [r[0] for r in rows]

def db_tenant_delete(tenant_id: str) -> bool:
    """Delete a tenant by UUID. Cascades to tenant_members. Returns True on success."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        cur.close()
        return deleted
    except Exception as e:
        print(f"[DB] Failed to delete tenant: {e}")
        return False

def db_tenant_list_all() -> List[dict]:
    """List all tenants (admin only)."""
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute(f"SELECT {_tenant_select_cols()} FROM tenants ORDER BY created_at DESC", ())
    rows = cur.fetchall()
    cur.close()
    return [_row_to_tenant(r) for r in rows]

def db_tenant_update_subscription(
    tenant_id: str,
    *,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    subscription_status: Optional[str] = None,
    plan: Optional[str] = None,
) -> bool:
    """Update tenant subscription fields (from Stripe webhook). Returns True on success."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        updates = []
        params = []
        if stripe_customer_id is not None:
            updates.append("stripe_customer_id = %s")
            params.append(stripe_customer_id)
        if stripe_subscription_id is not None:
            updates.append("stripe_subscription_id = %s")
            params.append(stripe_subscription_id)
        if subscription_status is not None:
            updates.append("subscription_status = %s")
            params.append(subscription_status)
        if plan is not None:
            updates.append("plan = %s")
            params.append(plan)
        if not updates:
            cur.close()
            return True
        params.append(tenant_id)
        cur.execute(f"UPDATE tenants SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[DB] Failed to update tenant subscription: {e}")
        return False

def db_tenant_set_billing_exempt(tenant_id: str, exempt_until: Optional[datetime]) -> bool:
    """Set billing_exempt_until for a tenant (admin). None clears exemption. Returns True on success."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE tenants SET billing_exempt_until = %s WHERE id = %s", (exempt_until, tenant_id))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[DB] Failed to set billing exempt: {e}")
        return False

def db_tenant_extend_trial(tenant_id: str, trial_ends_at: datetime) -> bool:
    """Set trial_ends_at for a tenant (admin). Returns True on success."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE tenants SET trial_ends_at = %s WHERE id = %s", (trial_ends_at, tenant_id))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[DB] Failed to extend trial: {e}")
        return False

def db_tenant_get_by_stripe_subscription_id(stripe_subscription_id: str) -> Optional[dict]:
    """Look up tenant by Stripe subscription ID (for webhook invoice.payment_failed)."""
    if not stripe_subscription_id:
        return None
    conn = _get_conn()
    if not conn:
        return None
    cur = conn.cursor()
    cur.execute(f"SELECT {_tenant_select_cols()} FROM tenants WHERE stripe_subscription_id = %s LIMIT 1", (stripe_subscription_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return _row_to_tenant(row)

def db_tenant_get_by_client_id(client_id: str) -> Optional[dict]:
    """Look up tenant by client_id."""
    if not client_id:
        return None
    conn = _get_conn()
    if not conn:
        return None
    cur = conn.cursor()
    cur.execute(f"SELECT {_tenant_select_cols()} FROM tenants WHERE client_id = %s LIMIT 1", (client_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return _row_to_tenant(row)

def db_audit_append(
    actor_type: str,
    action: str,
    *,
    actor_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    client_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """Append an audit event. Does not log full PII (e.g. no message bodies)."""
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        details_json = json.dumps(details) if details is not None else None
        cid = client_id if client_id is not None else _client_id()
        cur.execute("""
            INSERT INTO audit_events (actor_type, actor_id, action, resource_type, resource_id, client_id, details, ip, request_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        """, (actor_type, actor_id, action, resource_type, resource_id, cid or None, details_json, ip, request_id))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[DB] Failed to append audit: {e}")

def _normalize_phone(phone: str) -> str:
    return "".join(c for c in (phone or "") if c.isdigit())

# --- Appointments ---
def db_appointments_get_all() -> List[dict]:
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, email, phone, date, time, reason, status, source, created_at FROM appointments WHERE client_id = %s ORDER BY date, time",
        (_client_id(),)
    )
    rows = cur.fetchall()
    cur.close()
    return [
        {
            "id": r[0], "name": r[1], "email": r[2] or "", "phone": r[3] or "",
            "date": r[4], "time": r[5] or "", "reason": r[6] or "", "status": r[7],
            "source": r[8] or "manual", "created_at": r[9].isoformat() if r[9] else ""
        }
        for r in rows
    ]

def db_appointments_insert(data: dict) -> dict:
    conn = _get_conn()
    if not conn:
        raise RuntimeError("Database not available")
    cur = conn.cursor()
    cid = (data.get("client_id") or "").strip() or _client_id()
    print(f"[DB] db_appointments_insert client_id={cid} name={data.get('name')!r} date={data.get('date')} time={data.get('time')}")
    cur.execute("""
        INSERT INTO appointments (client_id, name, email, phone, date, time, reason, status, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, created_at
    """, (
        cid, data["name"], data.get("email", ""), data.get("phone", ""),
        data["date"], data.get("time", ""), data.get("reason", ""),
        data.get("status", "pending"), data.get("source", "manual")
    ))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    apt_id = row[0]
    print(f"[DB] db_appointments_insert OK id={apt_id} client_id={cid}")
    return {"id": apt_id, "created_at": row[1].isoformat() if row[1] else "", **data}

def db_appointments_update(appointment_id: int, **kwargs) -> Optional[dict]:
    conn = _get_conn()
    if not conn:
        return None
    allowed = ("status", "date", "time", "reason", "name", "email", "phone")
    updates = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            updates.append(f"{k} = %s")
            vals.append(v)
    if not updates:
        return None
    vals.append(appointment_id)
    vals.append(_client_id())
    cur = conn.cursor()
    cur.execute(
        f"UPDATE appointments SET {', '.join(updates)} WHERE id = %s AND client_id = %s RETURNING id, name, email, phone, date, time, reason, status, source, created_at",
        vals
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "email": row[2] or "", "phone": row[3] or "", "date": row[4], "time": row[5] or "", "reason": row[6] or "", "status": row[7], "source": row[8] or "manual", "created_at": row[9].isoformat() if row[9] else ""}

def db_appointments_get_by_id(appointment_id: int) -> Optional[dict]:
    conn = _get_conn()
    if not conn:
        return None
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, email, phone, date, time, reason, status, source, created_at FROM appointments WHERE id = %s AND client_id = %s",
        (appointment_id, _client_id())
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "email": row[2] or "", "phone": row[3] or "", "date": row[4], "time": row[5] or "", "reason": row[6] or "", "status": row[7], "source": row[8] or "manual", "created_at": row[9].isoformat() if row[9] else ""}

def db_appointments_max_id() -> int:
    conn = _get_conn()
    if not conn:
        return 0
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(id), 0) FROM appointments WHERE client_id = %s", (_client_id(),))
    row = cur.fetchone()
    cur.close()
    return row[0] if row else 0

def db_appointments_get_accepted_for_date(client_id: str, date: str) -> List[dict]:
    """Get accepted appointments for client_id and date (YYYY-MM-DD) with reminder_sent_at IS NULL."""
    if not client_id or not date:
        return []
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, email, phone, date, time, reason, status
        FROM appointments
        WHERE client_id = %s AND status = 'accepted' AND date = %s AND reminder_sent_at IS NULL
        ORDER BY time
    """, (client_id, date))
    rows = cur.fetchall()
    cur.close()
    return [
        {"id": r[0], "name": r[1], "email": r[2] or "", "phone": r[3] or "", "date": r[4], "time": r[5] or "", "reason": r[6] or "", "status": r[7]}
        for r in rows
    ]

def db_appointments_mark_reminder_sent(appointment_id: int, client_id: str) -> bool:
    """Atomically set reminder_sent_at if not already set. Returns True if updated."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE appointments SET reminder_sent_at = NOW()
            WHERE id = %s AND client_id = %s AND reminder_sent_at IS NULL
            RETURNING id
        """, (appointment_id, client_id))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row is not None
    except Exception as e:
        print(f"[DB] Failed to mark reminder sent: {e}")
        return False

def db_appointments_get_pending_by_phone(phone: str) -> Optional[dict]:
    """Return most recent pending_review appointment for this phone, or None."""
    conn = _get_conn()
    if not conn:
        return None
    norm = _normalize_phone(phone or "")
    if not norm:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, email, phone, date, time, reason, status, source, created_at
        FROM appointments
        WHERE client_id = %s AND status = 'pending_review'
          AND (regexp_replace(COALESCE(phone,''), '[^0-9]', '', 'g') = %s
               OR regexp_replace(COALESCE(phone,''), '[^0-9]', '', 'g') = right(%s, 10))
        ORDER BY created_at DESC
        LIMIT 1
    """, (_client_id(), norm, norm))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "email": row[2] or "", "phone": row[3] or "", "date": row[4], "time": row[5] or "", "reason": row[6] or "", "status": row[7], "source": row[8] or "manual", "created_at": row[9].isoformat() if row[9] else ""}

def db_appointments_get_by_phone_for_sms(phone: str) -> Optional[dict]:
    """Return most recent appointment for this phone with status pending_customer or pending_review (for SMS reply context and confirm flow)."""
    conn = _get_conn()
    if not conn:
        return None
    norm = _normalize_phone(phone or "")
    if not norm:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, email, phone, date, time, reason, status, source, created_at
        FROM appointments
        WHERE client_id = %s AND status IN ('pending_customer', 'pending_review')
          AND (regexp_replace(COALESCE(phone,''), '[^0-9]', '', 'g') = %s
               OR regexp_replace(COALESCE(phone,''), '[^0-9]', '', 'g') = right(%s, 10))
        ORDER BY created_at DESC
        LIMIT 1
    """, (_client_id(), norm, norm))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "email": row[2] or "", "phone": row[3] or "", "date": row[4], "time": row[5] or "", "reason": row[6] or "", "status": row[7], "source": row[8] or "manual", "created_at": row[9].isoformat() if row[9] else ""}

# --- SMS Sessions ---
def db_sms_session_get(phone: str, client_id: str) -> Optional[dict]:
    """Get SMS session for phone+client. Returns {messages, appointment_id} or None."""
    conn = _get_conn()
    if not conn:
        return None
    norm = _normalize_phone(phone or "")
    if not norm:
        return None
    cur = conn.cursor()
    cur.execute(
        "SELECT messages, appointment_id, updated_at FROM sms_sessions WHERE phone = %s AND client_id = %s",
        (norm, client_id)
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    msgs = row[0] if isinstance(row[0], list) else (json.loads(row[0]) if row[0] else [])
    return {"messages": msgs, "appointment_id": row[1], "updated_at": row[2]}

def db_sms_session_upsert(phone: str, client_id: str, messages: list, appointment_id: Optional[int] = None) -> None:
    """Insert or update SMS session."""
    conn = _get_conn()
    if not conn:
        return
    norm = _normalize_phone(phone or "")
    if not norm:
        return
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sms_sessions (phone, client_id, messages, appointment_id, updated_at)
        VALUES (%s, %s, %s::jsonb, %s, NOW())
        ON CONFLICT (phone, client_id) DO UPDATE SET
            messages = EXCLUDED.messages,
            appointment_id = COALESCE(EXCLUDED.appointment_id, sms_sessions.appointment_id),
            updated_at = NOW()
    """, (norm, client_id, json.dumps(messages), appointment_id))
    conn.commit()
    cur.close()

# --- Messages ---
def db_messages_get_all() -> List[dict]:
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute(
        "SELECT id, caller_name, caller_phone, message, urgency, status, created_at FROM messages WHERE client_id = %s ORDER BY created_at DESC",
        (_client_id(),)
    )
    rows = cur.fetchall()
    cur.close()
    return [
        {"id": r[0], "caller_name": r[1], "caller_phone": r[2], "message": r[3], "urgency": r[4], "status": r[5], "created_at": r[6].isoformat() if r[6] else ""}
        for r in rows
    ]

def db_messages_insert(data: dict) -> dict:
    conn = _get_conn()
    if not conn:
        raise RuntimeError("Database not available")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO messages (client_id, caller_name, caller_phone, message, urgency, status)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, created_at
    """, (_client_id(), data.get("caller_name", ""), data.get("caller_phone", ""), data.get("message", ""), data.get("urgency", "normal"), data.get("status", "unread")))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    return {"id": row[0], "created_at": row[1].isoformat() if row[1] else "", **data}

def db_messages_max_id() -> int:
    conn = _get_conn()
    if not conn:
        return 0
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(id), 0) FROM messages WHERE client_id = %s", (_client_id(),))
    row = cur.fetchone()
    cur.close()
    return row[0] if row else 0

# --- Usage tracking ---
def db_usage_get(client_id: str, month: str) -> Optional[dict]:
    """Get usage for client_id and month (YYYY-MM). Returns {voice_minutes, sms_count} or None."""
    if not client_id or not month:
        return None
    conn = _get_conn()
    if not conn:
        return None
    cur = conn.cursor()
    cur.execute(
        "SELECT voice_minutes, sms_count FROM tenant_usage WHERE client_id = %s AND month = %s",
        (client_id, month)
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return {"voice_minutes": 0, "sms_count": 0}
    return {"voice_minutes": row[0] or 0, "sms_count": row[1] or 0}

def db_usage_increment_voice(client_id: str, month: str, minutes: int) -> bool:
    """Atomically increment voice_minutes. Returns True on success."""
    if not client_id or not month or minutes < 0:
        return False
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tenant_usage (client_id, month, voice_minutes, sms_count)
            VALUES (%s, %s, %s, 0)
            ON CONFLICT (client_id, month) DO UPDATE SET
                voice_minutes = tenant_usage.voice_minutes + EXCLUDED.voice_minutes,
                updated_at = NOW()
        """, (client_id, month, minutes))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[DB] Failed to increment voice usage: {e}")
        return False

def db_usage_increment_sms(client_id: str, month: str) -> bool:
    """Atomically increment sms_count. Returns True on success."""
    if not client_id or not month:
        return False
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tenant_usage (client_id, month, voice_minutes, sms_count)
            VALUES (%s, %s, 0, 1)
            ON CONFLICT (client_id, month) DO UPDATE SET
                sms_count = tenant_usage.sms_count + 1,
                updated_at = NOW()
        """, (client_id, month))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[DB] Failed to increment SMS usage: {e}")
        return False

# --- Leads ---
def db_leads_insert(client_id: str, name: Optional[str], phone: str, reason: str, source: str) -> Optional[int]:
    """Insert a lead. Returns id or None on failure."""
    if not client_id or not phone or source not in ("call", "sms"):
        return None
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO leads (client_id, name, phone, reason, source)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (client_id, name or "", phone, reason or "", source))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] Failed to insert lead: {e}")
        return None

def db_leads_get_all(client_id: str, limit: int = 100) -> List[dict]:
    """Get leads for client_id, newest first."""
    if not client_id:
        return []
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, phone, reason, source, created_at
        FROM leads WHERE client_id = %s ORDER BY created_at DESC LIMIT %s
    """, (client_id, limit))
    rows = cur.fetchall()
    cur.close()
    return [
        {"id": r[0], "name": r[1] or "", "phone": r[2], "reason": r[3] or "", "source": r[4], "created_at": r[5].isoformat() if r[5] else ""}
        for r in rows
    ]

# --- SMS Automations ---
def db_sms_automations_get_all(client_id: str) -> List[dict]:
    """Get all sms_automations for client_id."""
    if not client_id:
        return []
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute("SELECT id, trigger, template, enabled, created_at FROM sms_automations WHERE client_id = %s ORDER BY id", (client_id,))
    rows = cur.fetchall()
    cur.close()
    return [{"id": r[0], "trigger": r[1], "template": r[2], "enabled": bool(r[3]), "created_at": r[4].isoformat() if r[4] else ""} for r in rows]

def db_sms_automations_count(client_id: str) -> int:
    """Count sms_automations for client_id."""
    if not client_id:
        return 0
    conn = _get_conn()
    if not conn:
        return 0
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sms_automations WHERE client_id = %s", (client_id,))
    row = cur.fetchone()
    cur.close()
    return row[0] if row else 0

def db_sms_automations_get_by_trigger(client_id: str, trigger: str) -> List[dict]:
    """Get enabled automations for client_id and trigger."""
    if not client_id or trigger not in ("after_inquiry", "post_call"):
        return []
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute(
        "SELECT id, trigger, template, enabled FROM sms_automations WHERE client_id = %s AND trigger = %s AND enabled = true",
        (client_id, trigger)
    )
    rows = cur.fetchall()
    cur.close()
    return [{"id": r[0], "trigger": r[1], "template": r[2], "enabled": bool(r[3])} for r in rows]

def db_sms_automations_insert(client_id: str, trigger: str, template: str, enabled: bool = True) -> Optional[int]:
    """Insert sms_automation. Returns id or None."""
    if not client_id or trigger not in ("after_inquiry", "post_call"):
        return None
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sms_automations (client_id, trigger, template, enabled) VALUES (%s, %s, %s, %s) RETURNING id",
            (client_id, trigger, template, enabled)
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] Failed to insert sms_automation: {e}")
        return None

def db_sms_automations_update(automation_id: int, client_id: str, template: Optional[str] = None, enabled: Optional[bool] = None) -> bool:
    """Update sms_automation. Returns True on success."""
    if not client_id:
        return False
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        updates = []
        params = []
        if template is not None:
            updates.append("template = %s")
            params.append(template)
        if enabled is not None:
            updates.append("enabled = %s")
            params.append(enabled)
        if not updates:
            cur.close()
            return True
        params.extend([automation_id, client_id])
        cur.execute(
            f"UPDATE sms_automations SET {', '.join(updates)} WHERE id = %s AND client_id = %s",
            params
        )
        conn.commit()
        cur.close()
        return cur.rowcount > 0 if hasattr(cur, 'rowcount') else True
    except Exception as e:
        print(f"[DB] Failed to update sms_automation: {e}")
        return False

def db_sms_automations_delete(automation_id: int, client_id: str) -> bool:
    """Delete sms_automation. Returns True on success."""
    if not client_id:
        return False
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sms_automations WHERE id = %s AND client_id = %s", (automation_id, client_id))
        conn.commit()
        deleted = cur.rowcount > 0
        cur.close()
        return deleted
    except Exception as e:
        print(f"[DB] Failed to delete sms_automation: {e}")
        return False

# --- Overage processed ---
def db_overage_processed_exists(client_id: str, month: str) -> bool:
    """Check if overage was already processed for this client/month."""
    if not client_id or not month:
        return False
    conn = _get_conn()
    if not conn:
        return False
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM overage_processed WHERE client_id = %s AND month = %s LIMIT 1", (client_id, month))
    row = cur.fetchone()
    cur.close()
    return row is not None

def db_overage_processed_insert(client_id: str, month: str) -> bool:
    """Record that overage was processed for this client/month."""
    if not client_id or not month:
        return False
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO overage_processed (client_id, month) VALUES (%s, %s) ON CONFLICT DO NOTHING", (client_id, month))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[DB] Failed to insert overage_processed: {e}")
        return False

# --- Call log ---
def db_call_log_append(entry: dict) -> None:
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO call_log (client_id, call_sid, from_number, to_number, start_iso, end_iso, outcome, duration_sec, category,
                recording_sid, recording_url, recording_duration_sec, recording_status, call_summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (call_sid) DO UPDATE SET
                end_iso = EXCLUDED.end_iso,
                outcome = COALESCE(EXCLUDED.outcome, call_log.outcome),
                duration_sec = EXCLUDED.duration_sec,
                recording_sid = COALESCE(EXCLUDED.recording_sid, call_log.recording_sid),
                recording_url = COALESCE(EXCLUDED.recording_url, call_log.recording_url),
                recording_duration_sec = COALESCE(EXCLUDED.recording_duration_sec, call_log.recording_duration_sec),
                recording_status = COALESCE(EXCLUDED.recording_status, call_log.recording_status),
                call_summary = COALESCE(EXCLUDED.call_summary, call_log.call_summary)
        """, (
            _client_id(), entry.get("call_sid"), entry.get("from_number"), entry.get("to_number"),
            entry.get("start_iso"), entry.get("end_iso"), entry.get("outcome"),
            entry.get("duration_sec"), entry.get("category"),
            entry.get("recording_sid"), entry.get("recording_url"), entry.get("recording_duration_sec"),
            entry.get("recording_status"), entry.get("call_summary"),
        ))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[DB] Failed to append call log: {e}")

def db_call_log_load(limit: int = 5000, days: Optional[int] = None) -> List[dict]:
    """Load call log. If days is set, only include entries from last N days."""
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cid = _client_id()
    cols = """call_sid, from_number, to_number, start_iso, end_iso, outcome, duration_sec, category, created_at,
        recording_sid, recording_url, recording_duration_sec, recording_status, call_summary"""
    if days is not None and days > 0:
        cur.execute(f"""
            SELECT {cols}
            FROM call_log
            WHERE client_id = %s AND created_at >= NOW() - make_interval(days => %s::int)
            ORDER BY created_at DESC LIMIT %s
        """, (cid, days, limit))
    else:
        cur.execute(f"""
            SELECT {cols}
            FROM call_log WHERE client_id = %s ORDER BY created_at DESC LIMIT %s
        """, (cid, limit))
    rows = cur.fetchall()
    cur.close()
    def _row(r):
        return {
            "call_sid": r[0], "from_number": r[1], "to_number": r[2], "start_iso": r[3], "end_iso": r[4],
            "outcome": r[5], "duration_sec": r[6], "category": r[7],
            "created_at": r[8].isoformat() if len(r) > 8 and r[8] else None,
            "recording_sid": r[9] if len(r) > 9 else None,
            "recording_url": r[10] if len(r) > 10 else None,
            "recording_duration_sec": r[11] if len(r) > 11 else None,
            "recording_status": r[12] if len(r) > 12 else None,
            "call_summary": r[13] if len(r) > 13 else None,
        }
    return [_row(r) for r in rows]


def db_call_log_update_recording(
    call_sid: str,
    client_id: str,
    recording_sid: Optional[str] = None,
    recording_url: Optional[str] = None,
    recording_duration_sec: Optional[int] = None,
    recording_status: Optional[str] = None,
) -> bool:
    """Upsert recording metadata. Row may not exist yet if Twilio callbacks before call_log_end."""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO call_log (client_id, call_sid, recording_sid, recording_url, recording_duration_sec, recording_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (call_sid) DO UPDATE SET
                recording_sid = COALESCE(EXCLUDED.recording_sid, call_log.recording_sid),
                recording_url = COALESCE(EXCLUDED.recording_url, call_log.recording_url),
                recording_duration_sec = COALESCE(EXCLUDED.recording_duration_sec, call_log.recording_duration_sec),
                recording_status = COALESCE(EXCLUDED.recording_status, call_log.recording_status)
        """, (client_id, call_sid, recording_sid, recording_url, recording_duration_sec, recording_status))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[DB] Failed to upsert call_log recording: {e}")
        return False


def db_call_log_update_summary(call_sid: str, client_id: str, call_summary: str) -> bool:
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE call_log SET call_summary = %s WHERE call_sid = %s AND client_id = %s",
            (call_summary, call_sid, client_id),
        )
        ok = cur.rowcount > 0
        conn.commit()
        cur.close()
        return ok
    except Exception as e:
        print(f"[DB] Failed to update call_log summary: {e}")
        return False


def db_call_log_get_client_id_by_call_sid(call_sid: str) -> Optional[str]:
    """Resolve tenant client_id for a call (e.g. async recording webhook)."""
    conn = _get_conn()
    if not conn or not call_sid:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT client_id FROM call_log WHERE call_sid = %s LIMIT 1", (call_sid,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] Failed to lookup call_log client_id: {e}")
        return None


def db_call_log_get_by_call_sid(client_id: str, call_sid: str) -> Optional[dict]:
    """Single row for playback auth check."""
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT call_sid, from_number, to_number, start_iso, end_iso, outcome, duration_sec, category, created_at,
                recording_sid, recording_url, recording_duration_sec, recording_status, call_summary
            FROM call_log WHERE call_sid = %s AND client_id = %s LIMIT 1
        """, (call_sid, client_id))
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        return {
            "call_sid": row[0], "from_number": row[1], "to_number": row[2], "start_iso": row[3], "end_iso": row[4],
            "outcome": row[5], "duration_sec": row[6], "category": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "recording_sid": row[9], "recording_url": row[10], "recording_duration_sec": row[11],
            "recording_status": row[12], "call_summary": row[13],
        }
    except Exception as e:
        print(f"[DB] Failed to get call_log row: {e}")
        return None

# --- Caller memory ---
def db_caller_memory_get(phone: str) -> Optional[dict]:
    conn = _get_conn()
    if not conn:
        return None
    key = _normalize_phone(phone)
    if not key:
        return None
    cur = conn.cursor()
    cur.execute("SELECT name, call_count, last_call_iso, last_reason, data FROM caller_memory WHERE phone = %s AND client_id = %s", (key, _client_id()))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    data = row[4]
    if isinstance(data, str):
        try:
            data = json.loads(data) if data else {}
        except Exception:
            data = {}
    return {"name": row[0], "call_count": row[1], "last_call_iso": row[2], "last_reason": row[3], **(data or {})}

def db_caller_memory_upsert(phone: str, name: Optional[str] = None, last_reason: Optional[str] = None, increment_count: bool = True) -> None:
    conn = _get_conn()
    if not conn:
        return
    key = _normalize_phone(phone)
    if not key:
        return
    cur = conn.cursor()
    cur.execute("SELECT call_count FROM caller_memory WHERE phone = %s AND client_id = %s", (key, _client_id()))
    row = cur.fetchone()
    now = datetime.now().isoformat()
    if row:
        count = row[0] + (1 if increment_count else 0)
        cur.execute("""
            UPDATE caller_memory SET name = COALESCE(%s, name), call_count = %s, last_call_iso = %s, last_reason = COALESCE(%s, last_reason), updated_at = NOW()
            WHERE phone = %s AND client_id = %s
        """, (name, count, now, last_reason, key, _client_id()))
    else:
        cur.execute("""
            INSERT INTO caller_memory (phone, client_id, name, call_count, last_call_iso, last_reason)
            VALUES (%s, %s, %s, 1, %s, %s)
        """, (key, _client_id(), name or "", now, last_reason or ""))
    conn.commit()
    cur.close()

# --- Booked slots ---
def db_booked_slots_load() -> List[dict]:
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute("SELECT date, time, appointment_id, duration_minutes FROM booked_slots WHERE client_id = %s", (_client_id(),))
    rows = cur.fetchall()
    cur.close()
    return [{"date": r[0], "time": r[1], "appointment_id": r[2], "duration_minutes": r[3] or 30} for r in rows]

def db_booked_slots_save(slots: List[dict]) -> None:
    conn = _get_conn()
    if not conn:
        return
    cur = conn.cursor()
    cur.execute("DELETE FROM booked_slots WHERE client_id = %s", (_client_id(),))
    for s in slots:
        cur.execute(
            "INSERT INTO booked_slots (client_id, date, time, appointment_id, duration_minutes) VALUES (%s, %s, %s, %s, %s)",
            (_client_id(), s["date"], s["time"], s["appointment_id"], s.get("duration_minutes", 30))
        )
    conn.commit()
    cur.close()
