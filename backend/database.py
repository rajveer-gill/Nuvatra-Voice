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
        _conn = psycopg2.connect(url)
    return _conn

def init_db() -> bool:
    """Initialize database: create tables if not exist. Returns True if DB is used."""
    global _use_db
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(url)
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
def db_tenant_create(client_id: str, name: str, twilio_phone_number: str, plan: str = "starter") -> Optional[dict]:
    """Create a tenant. Returns tenant dict or None on conflict."""
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tenants (client_id, name, twilio_phone_number, plan)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (client_id) DO NOTHING
            RETURNING id, client_id, name, twilio_phone_number, plan, created_at
        """, (client_id, name, twilio_phone_number, plan))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            return None
        return {"id": str(row[0]), "client_id": row[1], "name": row[2], "twilio_phone_number": row[3], "plan": row[4], "created_at": row[5].isoformat() if row[5] else None}
    except Exception as e:
        print(f"[DB] Failed to create tenant: {e}")
        return None

def db_tenant_get_by_phone(twilio_phone_number: str) -> Optional[dict]:
    """Look up tenant by Twilio phone number (E.164). Returns tenant or None."""
    conn = _get_conn()
    if not conn:
        return None
    cur = conn.cursor()
    # Normalize: Twilio sends E.164; try exact match and alternate normalization
    normalized = _normalize_e164(twilio_phone_number or "")
    cur.execute("""
        SELECT id, client_id, name, twilio_phone_number, plan
        FROM tenants WHERE twilio_phone_number IN (%s, %s)
        LIMIT 1
    """, (twilio_phone_number or "", normalized))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return {"id": str(row[0]), "client_id": row[1], "name": row[2], "twilio_phone_number": row[3], "plan": row[4]}

def db_tenant_get_by_id(tenant_id: str) -> Optional[dict]:
    """Look up tenant by UUID."""
    conn = _get_conn()
    if not conn:
        return None
    cur = conn.cursor()
    cur.execute("SELECT id, client_id, name, twilio_phone_number, plan FROM tenants WHERE id = %s", (tenant_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return {"id": str(row[0]), "client_id": row[1], "name": row[2], "twilio_phone_number": row[3], "plan": row[4]}

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
        SELECT t.id, t.client_id, t.name, t.twilio_phone_number, t.plan
        FROM tenants t
        JOIN tenant_members m ON m.tenant_id = t.id
        WHERE m.clerk_user_id = %s
        LIMIT 1
    """, (clerk_user_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return {"id": str(row[0]), "client_id": row[1], "name": row[2], "twilio_phone_number": row[3], "plan": row[4]}

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
    cur.execute("SELECT id, client_id, name, twilio_phone_number, plan, created_at FROM tenants ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close()
    return [{"id": str(r[0]), "client_id": r[1], "name": r[2], "twilio_phone_number": r[3], "plan": r[4], "created_at": r[5].isoformat() if r[5] else None} for r in rows]

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
    cur.execute("""
        INSERT INTO appointments (client_id, name, email, phone, date, time, reason, status, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, created_at
    """, (
        _client_id(), data["name"], data.get("email", ""), data.get("phone", ""),
        data["date"], data.get("time", ""), data.get("reason", ""),
        data.get("status", "pending"), data.get("source", "manual")
    ))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    return {"id": row[0], "created_at": row[1].isoformat() if row[1] else "", **data}

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

# --- Call log ---
def db_call_log_append(entry: dict) -> None:
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO call_log (client_id, call_sid, from_number, to_number, start_iso, end_iso, outcome, duration_sec, category)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (call_sid) DO UPDATE SET end_iso = EXCLUDED.end_iso, outcome = COALESCE(EXCLUDED.outcome, call_log.outcome), duration_sec = EXCLUDED.duration_sec
        """, (
            _client_id(), entry.get("call_sid"), entry.get("from_number"), entry.get("to_number"),
            entry.get("start_iso"), entry.get("end_iso"), entry.get("outcome"),
            entry.get("duration_sec"), entry.get("category")
        ))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[DB] Failed to append call log: {e}")

def db_call_log_load(limit: int = 5000) -> List[dict]:
    conn = _get_conn()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute("""
        SELECT call_sid, from_number, to_number, start_iso, end_iso, outcome, duration_sec, category
        FROM call_log WHERE client_id = %s ORDER BY created_at DESC LIMIT %s
    """, (_client_id(), limit))
    rows = cur.fetchall()
    cur.close()
    return [{"call_sid": r[0], "from_number": r[1], "to_number": r[2], "start_iso": r[3], "end_iso": r[4], "outcome": r[5], "duration_sec": r[6], "category": r[7]} for r in rows]

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
