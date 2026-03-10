import sys

from fastapi import FastAPI, HTTPException, Request, Form, Depends
from contextlib import asynccontextmanager
import asyncio
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional, List, Literal
import uuid
import logging
import openai

logger = logging.getLogger("nuvatra")
import os
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import hmac
import math
import time
import json
from pathlib import Path
import io
from urllib.parse import quote
import base64
# Twilio imports (optional - only needed for phone integration)
try:
    from twilio.twiml.voice_response import VoiceResponse
    from twilio.rest import Client as TwilioClient
    from twilio.request_validator import RequestValidator
    TWILIO_AVAILABLE = True
except ImportError:
    VoiceResponse = None
    TwilioClient = None
    RequestValidator = None
    TWILIO_AVAILABLE = False
    print("WARNING: Twilio not installed - phone features will be disabled. Install with: pip install twilio")

try:
    from plans import get_plan_limits
except ImportError:
    get_plan_limits = None  # type: ignore

try:
    from voice_preview import add_sentence_pauses
except ImportError:
    def add_sentence_pauses(text: str) -> str:
        return (text or "").strip()

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    stripe = None
    STRIPE_AVAILABLE = False

# Load .env from backend directory (where this script is located)
# Get the directory where this script is located
_this_file = Path(__file__).resolve()
_backend_dir = _this_file.parent

# The .env file is in the backend directory
env_path = _backend_dir / '.env'

# Load .env file
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    # Fallback: try default load_dotenv behavior
    load_dotenv()

# Structured logging: level from LOG_LEVEL env
_log_level = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
logger.setLevel(getattr(logging, _log_level, logging.INFO))
if not logger.handlers:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(levelname)s|%(name)s|%(message)s"))
    logger.addHandler(h)

# Verify API key is loaded
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print(f"ERROR: OPENAI_API_KEY not found!")
    print(f"Checked path: {env_path}")
    print(f"Path exists: {env_path.exists()}")
    print(f"Make sure your .env file is in the backend directory with OPENAI_API_KEY=your_key")
    raise ValueError(
        f"OPENAI_API_KEY not found! Checked: {env_path}\n"
        f"Make sure your .env file is in the backend directory with OPENAI_API_KEY=your_key"
    )
else:
    print(f"API Key loaded successfully (length: {len(api_key)})")


async def pre_warm_openai():
    """Pre-warm OpenAI client and generate greeting audio. Runs in background so server can bind immediately."""
    global greeting_audio_cache, got_it_audio_cache
    try:
        _ensure_openai_client()
        print("[WARM] Pre-warming OpenAI client...")
        await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
            temperature=0,
        )
        print("[OK] OpenAI client pre-warmed successfully")
        print("[TTS] Generating greeting audio with OpenAI TTS...")
        try:
            greeting_text = add_sentence_pauses(get_greeting_text())
        except NameError:
            greeting_text = "Thank you for calling. How can I help you today?"
        try:
            tts_speed = get_tts_speed()
        except NameError:
            tts_speed = 1.0
        greeting_audio = await asyncio.to_thread(
            client.audio.speech.create,
            model="tts-1-hd",
            voice="fable",
            input=greeting_text,
            speed=tts_speed,
        )
        greeting_audio_cache = greeting_audio.content
        print(f"[OK] Greeting audio generated and cached ({len(greeting_audio_cache)} bytes)")
        print("[TTS] Generating 'Got it, one moment' audio...")
        got_it_audio = await asyncio.to_thread(
            client.audio.speech.create,
            model="tts-1-hd",
            voice="fable",
            input=add_sentence_pauses("Got it, one moment."),
            speed=tts_speed,
        )
        got_it_audio_cache = got_it_audio.content
        print(f"[OK] 'Got it' audio generated and cached ({len(got_it_audio_cache)} bytes)")
    except Exception as e:
        print(f"[WARN] Pre-warm warning (non-critical): {e}")

async def keep_client_warm():
    """Background task to keep OpenAI client warm"""
    while True:
        await asyncio.sleep(120)
        try:
            await pre_warm_openai()
        except Exception as e:
            print(f"[WARN] Keep-warm error (non-critical): {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init DB first (in thread so it doesn't block the event loop), then pre-warm OpenAI
    db_task = asyncio.create_task(asyncio.to_thread(_init_db_background))
    warm_task = asyncio.create_task(pre_warm_openai())
    keep_warm_task = asyncio.create_task(keep_client_warm())
    yield
    for t in (db_task, warm_task, keep_warm_task):
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(title="Nuvatra Voice API", lifespan=lifespan)

# CORS middleware
# CORS configuration - allow localhost and production frontends
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://nuvatrasite.netlify.app",
    "https://nuvatra-voice.vercel.app",
    "https://nuvatrahq.com",
]
# Add production frontend URL if set
frontend_url = os.getenv("FRONTEND_URL")
if frontend_url:
    u = frontend_url.rstrip("/")
    if u not in allowed_origins:
        allowed_origins.append(u)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Set X-Request-ID for correlation; include in audit log and response."""
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = req_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response

# In-memory rate limit for public webhooks (phone/SMS) — 120 req/min per IP
_webhook_rate_limit: dict = {}  # ip -> list of timestamps
_webhook_rate_limit_lock = asyncio.Lock()
WEBHOOK_RATE_LIMIT_PER_MIN = 120

async def _webhook_rate_limit_check(request: Request) -> Optional[Response]:
    """Return 429 response if IP over limit for /api/phone/incoming or /api/sms/incoming; else None."""
    path = request.url.path
    if path not in ("/api/phone/incoming", "/api/sms/incoming"):
        return None
    ip = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc).timestamp()
    async with _webhook_rate_limit_lock:
        if ip not in _webhook_rate_limit:
            _webhook_rate_limit[ip] = []
        times = _webhook_rate_limit[ip]
        # Prune older than 1 minute
        times[:] = [t for t in times if now - t < 60]
        if len(times) >= WEBHOOK_RATE_LIMIT_PER_MIN:
            return Response(content="Too Many Requests", status_code=429)
        times.append(now)
    return None

@app.middleware("http")
async def webhook_rate_limit_middleware(request: Request, call_next):
    """Apply rate limit to phone/SMS webhooks."""
    if request.url.path in ("/api/phone/incoming", "/api/sms/incoming"):
        resp = await _webhook_rate_limit_check(request)
        if resp is not None:
            return resp
    return await call_next(request)

# CORS debug: only when DEBUG_CORS=1 (avoid file I/O and noise in production)
if os.getenv("DEBUG_CORS", "").strip() == "1":
    def _debug_log_payload(data: dict) -> None:
        import json as _json
        payload = {"sessionId": "e3c6b1", "timestamp": __import__("time").time() * 1000, "location": "main.py:CORS", "message": "request", "data": data}
        try:
            _log_path = _backend_dir.parent / "debug-e3c6b1.log"
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps(payload) + "\n")
        except Exception:
            pass
        print(f"[CORS-DEBUG] {payload}")
    @app.middleware("http")
    async def _cors_debug_middleware(request, call_next):
        origin = request.headers.get("origin") or ""
        _debug_log_payload({"method": request.method, "path": request.url.path, "origin": origin, "allowed_origins": allowed_origins})
        return await call_next(request)
    _debug_log_payload({"event": "startup", "allowed_origins": allowed_origins})

print(f"[INIT] Python {sys.version.split()[0]}, openai=={openai.__version__}")
sys.stdout.flush()

# Cache for pre-generated greeting audio
greeting_audio_cache = None
got_it_audio_cache = None  # Pre-cached "Got it, one moment" message
greeting_audio_url = None

# Lazy OpenAI client — created on first use so import doesn't block port binding
_openai_client = None

class _LazyOpenAIClient:
    """Proxy that creates the real OpenAI client on first attribute access."""
    def __getattr__(self, name):
        global _openai_client
        if _openai_client is None:
            print("[INIT] Creating OpenAI client (lazy)...")
            _openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            print("[OK] OpenAI client created successfully")
        return getattr(_openai_client, name)

client = _LazyOpenAIClient()

def _ensure_openai_client():
    """Eagerly create the client if not yet initialized."""
    global _openai_client
    if _openai_client is None:
        print("[INIT] Creating OpenAI client...")
        _openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        print("[OK] OpenAI client created successfully")


print("[INIT] Initializing Twilio...", flush=True)
# Initialize Twilio (optional - only if credentials are provided)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
TWILIO_SMS_FROM = os.getenv("TWILIO_SMS_FROM") or TWILIO_PHONE_NUMBER  # Same or separate number for SMS

twilio_client = None
if TWILIO_AVAILABLE and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        print(f"Twilio initialized successfully")
    except Exception as e:
        print(f"WARNING: Twilio initialization failed: {e}")
elif not TWILIO_AVAILABLE:
    print("WARNING: Twilio not installed - phone features disabled. Install with: pip install twilio")
elif not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
    print("WARNING: Twilio credentials not found - phone features will be disabled")

# Project root (parent of backend) for client configs
PROJECT_ROOT = _backend_dir.parent
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()

# Auth: Clerk JWT verification for multi-tenant
try:
    from auth import get_bearer_token, verify_clerk_token
except ImportError:
    get_bearer_token = lambda r: None
    verify_clerk_token = lambda t: ("", None)

# Database: PostgreSQL when DATABASE_URL is set (production)
# Import functions eagerly (no network); init_db() is deferred to background
USE_DB = False
_db_imported = False
try:
    from database import (
        init_db,
        set_request_client_id,
        _client_id as get_db_client_id,
        db_appointments_get_all,
        db_appointments_insert,
        db_appointments_update,
        db_appointments_get_by_id,
        db_appointments_max_id,
        db_messages_get_all,
        db_messages_insert,
        db_messages_max_id,
        db_call_log_append,
        db_call_log_load,
        db_caller_memory_get,
        db_caller_memory_upsert,
        db_booked_slots_load,
        db_booked_slots_save,
        db_tenant_get_by_phone,
        db_tenant_get_for_user,
        db_tenant_get_by_id,
        db_tenant_create,
        db_tenant_delete,
        db_tenant_get_members,
        db_tenant_member_add,
        db_tenant_list_all,
        db_tenant_update_subscription,
        db_tenant_set_billing_exempt,
        db_tenant_extend_trial,
        db_tenant_get_by_stripe_subscription_id,
        db_tenant_get_by_client_id,
        db_usage_get,
        db_usage_increment_voice,
        db_usage_increment_sms,
        db_leads_insert,
        db_leads_get_all,
        db_sms_automations_get_all,
        db_sms_automations_count,
        db_sms_automations_get_by_trigger,
        db_sms_automations_insert,
        db_sms_automations_update,
        db_sms_automations_delete,
        db_overage_processed_exists,
        db_overage_processed_insert,
        db_audit_append,
        db_sms_session_get,
        db_sms_session_upsert,
        db_appointments_get_pending_by_phone,
        db_appointments_get_accepted_for_date,
        db_appointments_mark_reminder_sent,
        db_tenant_list_all,
        db_ping,
    )
    _db_imported = True
    print("[INIT] Database module imported (connection deferred)", flush=True)
except ImportError as e:
    print(f"[WARN] Database module import failed: {e}", flush=True)

def _init_db_background():
    """Initialize DB connection in background thread so server starts immediately."""
    global USE_DB
    if not _db_imported or not os.getenv("DATABASE_URL"):
        return
    try:
        USE_DB = init_db()
        print(f"[INIT] Database ready (USE_DB={USE_DB})", flush=True)
    except Exception as e:
        print(f"[WARN] Database init failed (using in-memory): {e}", flush=True)

def audit_log(
    actor_type: str,
    action: str,
    *,
    actor_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    client_id: Optional[str] = None,
    details: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    """Append an audit event. No full PII (e.g. no message bodies)."""
    if not USE_DB:
        return
    try:
        ip = request.client.host if request and request.client else None
        request_id = getattr(request.state, "request_id", None) if request else None
        db_audit_append(
            actor_type=actor_type,
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            client_id=client_id,
            details=details,
            ip=ip,
            request_id=request_id,
        )
    except Exception:
        pass

# In-memory fallback when no database (dev / testing)
appointments: List[dict] = []
messages: List[dict] = []

def load_client_config(client_id: Optional[str] = None):
    """Load business config from clients/<client_id>/config.json. Uses request-scoped client_id if not passed."""
    cid = (client_id or get_db_client_id()).strip()
    if not cid:
        return None
    config_path = PROJECT_ROOT / "clients" / cid / "config.json"
    if not config_path.exists():
        print(f"WARNING: Client config not found: {config_path}")
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Normalize to get_business_info() shape
        forwarding = (data.get("forwarding_phone") or os.getenv("BUSINESS_FORWARDING_PHONE") or "")
        if not forwarding and data.get("locations"):
            forwarding = data["locations"][0].get("forwarding_phone", "")
        info = {
            "name": data.get("business_name", data.get("name", "Business")),
            "hours": data.get("hours", ""),
            "phone": data.get("phone", ""),
            "forwarding_phone": forwarding,
            "email": data.get("email", ""),
            "address": data.get("address", ""),
            "departments": data.get("departments", ["General"]),
            "menu_link": data.get("menu_link", ""),
            "services": data.get("services", []),
            "specials": data.get("specials", []),
            "reservation_rules": data.get("reservation_rules", []),
            "staff": data.get("staff", []),
            "locations": data.get("locations", []),
            "greeting": data.get("greeting", "Thank you for calling. How can I help you today?"),
            "plan": data.get("plan", "starter"),
            "voice": data.get("voice", "fable"),
            "speed": float(data.get("speed", 1.0)) if data.get("speed") is not None else 1.0,
            "receptionist_name": data.get("receptionist_name", ""),
        }
        print(f"Loaded client config: {cid} ({info['name']})")
        return info
    except Exception as e:
        print(f"WARNING: Failed to load client config: {e}")
        return None

# Business configuration: loaded per-request (multi-tenant) or at startup (single-tenant)
_DEMO_BUSINESS_INFO = {
        "name": "Nuvatra Demo Restaurant",
        "hours": "Monday-Thursday: 11 AM - 9 PM, Friday-Saturday: 11 AM - 10 PM, Sunday: 12 PM - 8 PM",
        "phone": "(925) 481-5386",
        "forwarding_phone": os.getenv("BUSINESS_FORWARDING_PHONE", "+19259978995"),
        "email": "info@nuvatrademo.com",
        "address": "123 Main Street, City, State 12345",
        "departments": ["Reservations", "Takeout", "Catering", "General"],
        "menu_link": "https://example.com/menu",
        "services": ["Dine-in", "Takeout", "Delivery", "Catering", "Private Events"],
        "specials": [
            "Happy Hour: 4 PM - 6 PM daily - 20% off appetizers",
            "Weekend Brunch: Saturday & Sunday 11 AM - 2 PM",
            "Family Night: Tuesday - Kids eat free with adult entree"
        ],
        "reservation_rules": [
            "Reservations recommended for parties of 6 or more",
            "Call ahead for same-day reservations",
            "Large parties (10+) require 48-hour notice"
        ],
        "staff": [],
        "locations": [],
        "greeting": "Thank you for calling. How can I help you today?",
        "plan": "starter",
        "voice": "fable",
        "speed": 1.0,
        "receptionist_name": "",
    }

def _default_business_info_for_tenant() -> Optional[dict]:
    """Build minimal business info from the tenant DB record when no config file exists."""
    if not USE_DB:
        return None
    cid = get_db_client_id()
    if not cid or cid == "default":
        return None
    try:
        from database import _get_conn
        conn = _get_conn()
        if not conn:
            return None
        cur = conn.cursor()
        cur.execute("SELECT name, twilio_phone_number, plan FROM tenants WHERE client_id = %s", (cid,))
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        return {
            "name": row[0] or "",
            "hours": "",
            "phone": row[1] or "",
            "forwarding_phone": "",
            "email": "",
            "address": "",
            "departments": [],
            "menu_link": "",
            "services": [],
            "specials": [],
            "reservation_rules": [],
            "staff": [],
            "locations": [],
            "greeting": "",
            "plan": row[2] or "starter",
            "voice": "fable",
            "speed": 1.0,
            "receptionist_name": "",
        }
    except Exception:
        return None

def get_business_info() -> dict:
    """Get business config for current request (multi-tenant) or env CLIENT_ID (single-tenant)."""
    cfg = load_client_config()
    if cfg:
        if not cfg.get("phone") and USE_DB:
            cid = get_db_client_id()
            if cid:
                tenant = db_tenant_get_by_client_id(cid)
                if tenant:
                    cfg["phone"] = tenant.get("twilio_phone_number") or ""
        return cfg
    tenant_info = _default_business_info_for_tenant()
    if tenant_info:
        return tenant_info
    return _DEMO_BUSINESS_INFO

def get_tts_voice() -> str:
    """Voice for TTS (phone/SMS). From business config or default fable."""
    return get_business_info().get("voice", "fable") or "fable"

def get_tts_speed() -> float:
    """Speaking speed for TTS (OpenAI allows 0.25–4.0). From business config or default 1.0."""
    try:
        s = float(get_business_info().get("speed", 1.0))
        return max(0.25, min(4.0, s))
    except (TypeError, ValueError):
        return 1.0

def get_greeting_text() -> str:
    """Greeting for phone (uses client config if set)."""
    info = get_business_info()
    raw = info.get("greeting") or "Thank you for calling. How can I help you today?"
    try:
        return raw.format(business_name=info.get("name", "us"))
    except KeyError:
        return raw

class ConversationRequest(BaseModel):
    message: str
    session_id: str
    conversation_history: Optional[List[dict]] = []

class ConversationResponse(BaseModel):
    response: str
    action: Optional[str] = None
    data: Optional[dict] = None

class AppointmentRequest(BaseModel):
    name: str
    email: str
    phone: str
    date: str
    time: str
    reason: str
    source: Optional[str] = "manual"  # "receptionist" | "manual"

class AppointmentUpdate(BaseModel):
    status: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    reason: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

class MessageRequest(BaseModel):
    caller_name: str
    caller_phone: str
    message: str
    urgency: str = "normal"

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "fable"  # nova, alloy, echo, fable, onyx, shimmer
    speed: Optional[float] = None  # OpenAI 0.25–4.0; if omitted uses business config

def _ensure_db_ready():
    """Block briefly to let background init_db finish if it hasn't yet."""
    global USE_DB
    if USE_DB or not _db_imported or not os.getenv("DATABASE_URL"):
        return
    import time
    for _ in range(20):
        if USE_DB:
            return
        time.sleep(0.5)
    # Last resort: try init synchronously
    try:
        USE_DB = init_db()
    except Exception:
        pass

def _clerk_fetch_user_tenant_id(clerk_user_id: str) -> Optional[str]:
    """Call Clerk Backend API to get tenant_id from the user's public_metadata.
    Used as a fallback when the JWT doesn't contain public_metadata."""
    clerk_secret = os.getenv("CLERK_SECRET_KEY", "").strip()
    if not clerk_secret:
        return None
    try:
        import httpx
        resp = httpx.get(
            f"https://api.clerk.com/v1/users/{clerk_user_id}",
            headers={"Authorization": f"Bearer {clerk_secret}"},
            timeout=5.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return (data.get("public_metadata") or {}).get("tenant_id")
    except Exception as e:
        print(f"[Auth] Clerk user lookup failed for {clerk_user_id}: {e}")
    return None

def require_tenant(request: Request):
    """
    Dependency: multi-tenant mode requires Bearer token; single-tenant uses CLIENT_ID env.
    Sets request client_id context for database operations.
    """
    jwks_url = os.getenv("CLERK_JWKS_URL", "").strip()
    if not jwks_url:
        return None
    token = get_bearer_token(request)
    if not token:
        audit_log("user", "auth_failure", details={"reason": "no_token"}, request=request)
        raise HTTPException(status_code=401, detail="Authorization required")
    user_id, tenant_id_from_meta = verify_clerk_token(token)
    _ensure_db_ready()
    tenant = None
    if tenant_id_from_meta and USE_DB:
        tenant = db_tenant_get_by_id(tenant_id_from_meta)
        if tenant and user_id:
            db_tenant_member_add(user_id, tenant["id"])
    if not tenant and USE_DB:
        tenant = db_tenant_get_for_user(user_id)
    if not tenant and USE_DB:
        # JWT didn't have metadata and user isn't in tenant_members yet.
        # Fetch tenant_id from Clerk Backend API (one-time for new invites).
        api_tenant_id = _clerk_fetch_user_tenant_id(user_id)
        if api_tenant_id:
            tenant = db_tenant_get_by_id(api_tenant_id)
            if tenant:
                db_tenant_member_add(user_id, tenant["id"])
                print(f"[Auth] Auto-linked user {user_id} to tenant {tenant['id']} via Clerk API")
    if not tenant:
        audit_log("user", "auth_failure", actor_id=user_id, details={"reason": "no_tenant"}, request=request)
        raise HTTPException(status_code=403, detail="No tenant assigned to your account")
    set_request_client_id(tenant["client_id"])
    return tenant

def require_admin(request: Request):
    """Dependency: require Bearer token and admin user (user_id in ADMIN_CLERK_USER_IDS)."""
    token = get_bearer_token(request)
    if not token:
        audit_log("admin", "auth_failure", details={"reason": "no_token"}, request=request)
        raise HTTPException(status_code=401, detail="Authorization required")
    user_id, _ = verify_clerk_token(token)
    admin_ids = [x.strip() for x in (os.getenv("ADMIN_CLERK_USER_IDS") or "").split(",") if x.strip()]
    if not admin_ids:
        audit_log("admin", "auth_failure", actor_id=user_id, details={"reason": "admin_not_configured"}, request=request)
        raise HTTPException(status_code=403, detail="Admin not configured")
    if user_id not in admin_ids:
        audit_log("admin", "auth_failure", actor_id=user_id, details={"reason": "not_admin"}, request=request)
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id

def get_tenant_subscription_state(tenant: Optional[dict]) -> dict:
    """Return subscription state for the tenant. If tenant is None (single-tenant), can_use_app is True."""
    if not tenant:
        return {"can_use_app": True, "trial_ends_at": None, "subscription_status": None, "plan": "starter", "billing_exempt_until": None}
    if not USE_DB:
        return {"can_use_app": True, "trial_ends_at": None, "subscription_status": tenant.get("subscription_status"), "plan": tenant.get("plan", "starter"), "billing_exempt_until": None}
    now = datetime.now(timezone.utc)
    trial_ends_at = tenant.get("trial_ends_at")
    subscription_status = tenant.get("subscription_status") or "trialing"
    billing_exempt_until = tenant.get("billing_exempt_until")
    plan = tenant.get("plan") or "free"
    exempt_active = False
    if billing_exempt_until:
        try:
            exempt_dt = datetime.fromisoformat(billing_exempt_until.replace("Z", "+00:00")) if isinstance(billing_exempt_until, str) else billing_exempt_until
            if exempt_dt.tzinfo is None:
                exempt_dt = exempt_dt.replace(tzinfo=timezone.utc)
            exempt_active = now < exempt_dt
        except Exception:
            pass
    trial_active = False
    if trial_ends_at and subscription_status == "trialing":
        try:
            trial_dt = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00")) if isinstance(trial_ends_at, str) else trial_ends_at
            if trial_dt.tzinfo is None:
                trial_dt = trial_dt.replace(tzinfo=timezone.utc)
            trial_active = now < trial_dt
        except Exception:
            pass
    paid_active = subscription_status == "active"
    can_use_app = exempt_active or trial_active or paid_active
    return {
        "can_use_app": can_use_app,
        "trial_ends_at": trial_ends_at,
        "subscription_status": subscription_status,
        "plan": plan,
        "billing_exempt_until": billing_exempt_until,
    }

def require_active_subscription(tenant: Optional[dict] = Depends(require_tenant)):
    """Dependency: after require_tenant, require that tenant can use the app (trial or paid or exempt)."""
    state = get_tenant_subscription_state(tenant)
    if not state.get("can_use_app"):
        raise HTTPException(
            status_code=403,
            detail={"code": "SUBSCRIPTION_REQUIRED", "message": "Subscription required. Your trial has ended. Please choose a plan to continue."},
            headers={"X-Subscription-Required": "true"},
        )
    return tenant

def _phone_to_e164(phone: str) -> Optional[str]:
    """Convert to E.164 for Twilio SMS (e.g. +15551234567). Returns None if too short."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) >= 10:
        return f"+{digits}"
    return None

def send_sms(to_phone: str, body: str, from_override: Optional[str] = None) -> bool:
    """Send SMS via Twilio. from_override: use this number as From (for multi-tenant replies from business number).
    Records usage via db_usage_increment_sms when client_id is set."""
    if not TWILIO_AVAILABLE or not twilio_client:
        print("SMS skipped: Twilio not configured")
        return False
    from_num = (from_override or TWILIO_SMS_FROM or "").strip()
    if not from_num:
        print("SMS skipped: SMS from number missing (set TWILIO_SMS_FROM or pass from_override)")
        return False
    e164 = _phone_to_e164(to_phone or "")
    if not e164:
        print(f"SMS skipped: invalid or short phone: {to_phone}")
        return False
    last_err = None
    for attempt in range(3):
        try:
            twilio_client.messages.create(from_=from_num, to=e164, body=body)
            # Record SMS usage for billing (graceful degradation)
            if USE_DB:
                cid = get_db_client_id()
                if cid and cid != "default":
                    try:
                        month = datetime.now(timezone.utc).strftime("%Y-%m")
                        db_usage_increment_sms(cid, month)
                    except Exception as e:
                        logger.error("SMS usage increment failed: %s", e)
            return True
        except Exception as e:
            last_err = e
            if attempt < 2:
                import time
                time.sleep(2 ** attempt)
    print(f"SMS send failed after retries: {last_err}")
    return False

def _validate_twilio_webhook(request: Request, form_data: dict) -> bool:
    """Validate X-Twilio-Signature so only Twilio can trigger webhooks. Returns True if valid or if auth token not set (backward compat)."""
    auth_token = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    if not auth_token:
        return True
    if not TWILIO_AVAILABLE or not RequestValidator:
        return True
    sig = request.headers.get("X-Twilio-Signature", "")
    if not sig:
        return False
    url = str(request.url)
    params = dict(form_data) if hasattr(form_data, "keys") else {k: v for k, v in form_data.items()}
    try:
        validator = RequestValidator(auth_token)
        return validator.validate(url, params, sig)
    except Exception as e:
        print(f"Twilio signature validation error: {e}")
        return False

def get_client_data_dir() -> Optional[Path]:
    """Return Path to client data directory (for call_log, caller_memory). None if no client_id."""
    cid = get_db_client_id()
    if not cid or cid == "default":
        return None
    d = PROJECT_ROOT / "clients" / cid
    d.mkdir(parents=True, exist_ok=True)
    return d

def normalize_phone(phone: str) -> str:
    """Normalize to E.164-ish key (digits only, no +)."""
    return "".join(c for c in phone if c.isdigit())

def get_caller_memory(phone: str) -> Optional[dict]:
    """Load caller memory for repeat-caller recognition. Returns None or {name, call_count, last_call_iso, last_reason}."""
    if USE_DB:
        return db_caller_memory_get(phone)
    data_dir = get_client_data_dir()
    if not data_dir:
        return None
    path = data_dir / "caller_memory.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        key = normalize_phone(phone)
        return data.get(key)
    except Exception:
        return None

def update_caller_memory(phone: str, name: Optional[str] = None, last_reason: Optional[str] = None):
    """Update caller memory after a call (increment count, set last call time and optional reason)."""
    if USE_DB:
        db_caller_memory_upsert(phone, name=name, last_reason=last_reason)
        return
    data_dir = get_client_data_dir()
    if not data_dir:
        return
    path = data_dir / "caller_memory.json"
    data = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    key = normalize_phone(phone)
    entry = data.setdefault(key, {"name": "", "call_count": 0, "last_call_iso": "", "last_reason": ""})
    entry["call_count"] = entry.get("call_count", 0) + 1
    entry["last_call_iso"] = datetime.now().isoformat()
    if name:
        entry["name"] = name
    if last_reason is not None:
        entry["last_reason"] = last_reason
    data[key] = entry
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save caller memory: {e}")

def get_staff_phone_by_name(name: str) -> Optional[str]:
    """Return E.164 phone for staff member by name (case-insensitive match)."""
    staff = get_business_info().get("staff") or []
    name_clean = name.strip().lower()
    for s in staff:
        if s.get("name", "").strip().lower() == name_clean:
            phone = (s.get("phone") or "").strip()
            if phone:
                return phone
    return None

def parse_transfer_to(ai_text: str) -> Optional[str]:
    """If AI responded with TRANSFER_TO: Name, return the name; else None."""
    if not ai_text:
        return None
    t = ai_text.strip()
    prefix = "TRANSFER_TO:"
    if t.upper().startswith(prefix):
        return t[len(prefix):].strip()
    return None

# Call log (Pro analytics): in-memory index by call_sid, persisted to JSON
call_log_entries = {}  # call_sid -> {from_number, to_number, start_iso, outcome, ...}
CALL_LOG_MAX_ENTRIES = 5000

def call_log_start(call_sid: str, from_number: str, to_number: str):
    """Record call start. Outcome set when we forward or in status callback."""
    call_log_entries[call_sid] = {
        "call_sid": call_sid,
        "from_number": from_number,
        "to_number": to_number,
        "start_iso": datetime.now().isoformat(),
        "outcome": None,
        "end_iso": None,
        "duration_sec": None,
        "category": None,
    }

def call_log_set_outcome(call_sid: str, outcome: str):
    """Set outcome: 'forwarded', 'answered_by_ai', 'missed', 'error', 'no-answer'."""
    if call_sid in call_log_entries:
        call_log_entries[call_sid]["outcome"] = outcome

def call_log_end(call_sid: str):
    """Write completed call to persistent log and remove from in-memory."""
    if call_sid not in call_log_entries:
        return
    entry = call_log_entries[call_sid].copy()
    entry["end_iso"] = datetime.now().isoformat()
    start_s = entry.get("start_iso")
    if start_s:
        try:
            start_dt = datetime.fromisoformat(start_s.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(entry["end_iso"].replace("Z", "+00:00"))
            entry["duration_sec"] = int((end_dt - start_dt).total_seconds())
        except Exception:
            pass
    if not entry.get("outcome"):
        entry["outcome"] = "answered_by_ai"
    if USE_DB:
        db_call_log_append(entry)
    else:
        data_dir = get_client_data_dir()
        if data_dir:
            path = data_dir / "call_log.json"
            log_list = []
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        log_list = json.load(f)
                except Exception:
                    pass
            log_list.append(entry)
            if len(log_list) > CALL_LOG_MAX_ENTRIES:
                log_list = log_list[-CALL_LOG_MAX_ENTRIES:]
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(log_list, f, indent=2)
            except Exception as e:
                print(f"Failed to save call log: {e}")
    del call_log_entries[call_sid]

# Booked slots (Zenoti-style: avoid double-book; inject into AI prompt)
DEFAULT_SLOT_DURATION_MINUTES = 30

def _load_booked_slots() -> List[dict]:
    """Load booked slots from client data dir. Each entry: {date, time, appointment_id, duration_minutes?}."""
    if USE_DB:
        return db_booked_slots_load()
    data_dir = get_client_data_dir()
    if not data_dir:
        return []
    path = data_dir / "booked_slots.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_booked_slots(slots: List[dict]) -> None:
    if USE_DB:
        db_booked_slots_save(slots)
        return
    data_dir = get_client_data_dir()
    if not data_dir:
        return
    path = data_dir / "booked_slots.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(slots, f, indent=2)
    except Exception as e:
        print(f"Failed to save booked_slots: {e}")

def get_booked_slots(date: str) -> List[dict]:
    """Return slots already booked for the given date (YYYY-MM-DD)."""
    slots = _load_booked_slots()
    return [s for s in slots if s.get("date") == date]

def _slot_overlaps(
    start_a: str, duration_a: int,
    start_b: str, duration_b: int
) -> bool:
    """True if two time windows overlap. start_* is HH:MM."""
    def to_minutes(t: str) -> int:
        parts = t.strip().split(":")
        h = int(parts[0]) if parts else 0
        m = int(parts[1]) if len(parts) > 1 else 0
        return h * 60 + m
    a_start = to_minutes(start_a)
    a_end = a_start + duration_a
    b_start = to_minutes(start_b)
    b_end = b_start + duration_b
    return a_start < b_end and b_start < a_end

def is_slot_available(
    date: str, time: str, duration_minutes: int = DEFAULT_SLOT_DURATION_MINUTES
) -> bool:
    """True if no overlapping booking for this date+time."""
    slots = get_booked_slots(date)
    for s in slots:
        d = s.get("duration_minutes") or DEFAULT_SLOT_DURATION_MINUTES
        if _slot_overlaps(time, duration_minutes, s.get("time", ""), d):
            return False
    return True

def reserve_slot(
    date: str, time: str, appointment_id: int,
    duration_minutes: int = DEFAULT_SLOT_DURATION_MINUTES
) -> None:
    """Record a slot as booked when creating an appointment."""
    slots = _load_booked_slots()
    slots.append({
        "date": date,
        "time": time,
        "appointment_id": appointment_id,
        "duration_minutes": duration_minutes,
    })
    _save_booked_slots(slots)

def release_slot(appointment_id: int) -> None:
    """Remove slot when appointment is rejected or cancelled."""
    slots = _load_booked_slots()
    slots = [s for s in slots if s.get("appointment_id") != appointment_id]
    _save_booked_slots(slots)

def get_booked_slots_prompt_text(days_ahead: int = 7) -> str:
    """Build a short line for the system prompt: already booked slots for today + days_ahead."""
    from datetime import timedelta
    today = datetime.now().date()
    parts = []
    for d in range(days_ahead):
        day = today + timedelta(days=d)
        date_str = day.isoformat()
        slots = get_booked_slots(date_str)
        if slots:
            times = [s.get("time", "") for s in slots if s.get("time")]
            if times:
                parts.append(f"{date_str} at {', '.join(times)}")
    if not parts:
        return ""
    return "Booked slots (do not double-book): " + "; ".join(parts) + ". If the caller requests any of these times, say that slot is taken and suggest another time or another stylist."

def _suggests_booking(text: str) -> bool:
    """True if the message suggests the caller wants to book/appointment/reservation."""
    if not text or len(text.strip()) < 2:
        return False
    t = text.lower()
    return any(k in t for k in ("book", "appointment", "reservation", "reserve", "schedule", "available", "slot", "time for"))

def parse_booking(ai_text: str) -> Optional[dict]:
    """If AI responded with BOOKING: name|phone|email|date|time|reason, return dict; else None."""
    if not ai_text or "BOOKING:" not in ai_text:
        return None
    line = ai_text.strip()
    for part in line.split("\n"):
        part = part.strip()
        if part.upper().startswith("BOOKING:"):
            rest = part[len("BOOKING:"):].strip()
            vals = [v.strip() for v in rest.split("|")]
            if len(vals) >= 5:
                return {
                    "name": vals[0] if len(vals) > 0 else "",
                    "phone": vals[1] if len(vals) > 1 else "",
                    "email": vals[2] if len(vals) > 2 else "",
                    "date": vals[3] if len(vals) > 3 else "",
                    "time": vals[4] if len(vals) > 4 else "",
                    "reason": vals[5] if len(vals) > 5 else "",
                }
            break
    return None

def _create_appointment_from_booking(booking: dict) -> Optional[dict]:
    """Create appointment from parsed BOOKING; check slot; return appointment_data or None (slot taken)."""
    date = (booking.get("date") or "").strip()
    time = (booking.get("time") or "").strip()
    name = (booking.get("name") or "").strip()
    if not name or not date or not time:
        return None
    if not is_slot_available(date, time):
        return None
    appointment_data = {
        "name": name,
        "email": (booking.get("email") or "").strip(),
        "phone": (booking.get("phone") or "").strip(),
        "date": date,
        "time": time,
        "reason": (booking.get("reason") or "").strip() or "—",
        "source": "receptionist",
        "status": "pending_review",
    }
    if USE_DB:
        row = db_appointments_insert(appointment_data)
        apt_id = row["id"]
    else:
        apt_id = len(appointments) + 1
        appointment_data["id"] = apt_id
        appointment_data["created_at"] = datetime.now().isoformat()
        appointments.append(appointment_data)
    reserve_slot(date, time, apt_id)
    appointment_data["id"] = apt_id
    appointment_data.setdefault("created_at", datetime.now().isoformat())
    return appointment_data

def uses_non_latin_script(language_name: str) -> bool:
    """
    Check if a language uses a non-Latin script (where Twilio transcription struggles).
    Returns True for languages like Japanese, Punjabi, Chinese, Arabic, Hindi, etc.
    """
    non_latin_languages = {
        'Japanese', 'Punjabi', 'Chinese', 'Hindi', 'Arabic', 'Russian', 
        'Korean', 'Thai', 'Vietnamese', 'Bengali', 'Tamil', 'Telugu',
        'Gujarati', 'Kannada', 'Malayalam', 'Marathi', 'Urdu', 'Hebrew',
        'Greek', 'Georgian', 'Armenian', 'Khmer', 'Lao', 'Myanmar',
        'Tibetan', 'Mongolian', 'Nepali', 'Sinhala'
    }
    return language_name in non_latin_languages

def get_twilio_language_code(language_name: str) -> str:
    """
    Map language name to Twilio language code for speech recognition.
    Returns Twilio language code (e.g., 'es-ES', 'en-US', 'hi-IN').
    Defaults to 'en-US' if language not supported.
    """
    language_map = {
        'English': 'en-US',
        'Spanish': 'es-ES',
        'French': 'fr-FR',
        'German': 'de-DE',
        'Italian': 'it-IT',
        'Portuguese': 'pt-PT',
        'Chinese': 'zh-CN',
        'Japanese': 'ja-JP',
        'Korean': 'ko-KR',
        'Hindi': 'hi-IN',
        'Punjabi': 'pa-IN',  # Punjabi (Gurmukhi)
        'Arabic': 'ar-SA',
        'Russian': 'ru-RU',
        'Dutch': 'nl-NL',
        'Polish': 'pl-PL',
        'Turkish': 'tr-TR',
        'Swedish': 'sv-SE',
        'Norwegian': 'nb-NO',
        'Danish': 'da-DK',
        'Finnish': 'fi-FI',
        'Greek': 'el-GR',
        'Czech': 'cs-CZ',
        'Romanian': 'ro-RO',
        'Hungarian': 'hu-HU',
        'Thai': 'th-TH',
        'Vietnamese': 'vi-VN',
        'Indonesian': 'id-ID',
        'Malay': 'ms-MY',
    }
    
    # Try exact match first
    if language_name in language_map:
        return language_map[language_name]
    
    # Try case-insensitive match
    for key, code in language_map.items():
        if key.lower() == language_name.lower():
            return code
    
    # Default to English if not found
    return 'en-US'

async def generate_response_async(call_sid: str, call_data: dict, detected_lang: str, base_url: str):
    """
    Background task to generate GPT response and TTS audio.
    Updates response_status when ready.
    """
    try:
        print(f"🤖 Generating response for call {call_sid}...")
        
        # Booking context: include booked slots when conversation suggests booking
        include_slots = any(
            _suggests_booking(m.get("content") or "")
            for m in call_data["conversation_history"]
            if m.get("role") == "user"
        )
        messages = [
            {"role": "system", "content": get_system_prompt(detected_lang, call_data.get("caller_memory"), include_booked_slots=include_slots)}
        ]
        messages.extend(call_data["conversation_history"])
        
        ai_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.8,
            max_tokens=80,
            stream=False
        )
        
        ai_text = ai_response.choices[0].message.content
        print(f"✅ GPT response generated: {ai_text[:50]}...")
        
        # BOOKING: create appointment from AI output if present; replace response with confirmation or slot-taken message
        booking = parse_booking(ai_text)
        if booking:
            # Use caller's phone from Twilio when available (don't require asking)
            if call_data.get("from_number"):
                booking["phone"] = (booking.get("phone") or "").strip() or call_data["from_number"]
            apt = _create_appointment_from_booking(booking)
            if apt:
                call_data["appointment_created"] = True
                ai_text = f"You're all set! We have you down for {apt['date']} at {apt['time']}. The store will confirm shortly."
                # Send caller a text: human-like, full details, invite reply to confirm or change
                thanks_msg = (
                    f"Hey! Your reservation is pending. Here's what we have:\n"
                    f"Name: {apt.get('name', '')}\n"
                    f"Date: {apt.get('date', '')}\n"
                    f"Time: {apt.get('time', '')}\n"
                    f"Service: {apt.get('reason', '')}\n\n"
                    f"Does this look right? Just reply to confirm, or let us know if you need to change anything. "
                    f"We'll text you once the business confirms!"
                )
                to_number = apt.get("phone") or ""
                from_number = call_data.get("to_number") if call_data else None
                send_sms(to_number, thanks_msg, from_override=from_number)
            else:
                ai_text = "That time slot just got booked. Would you like to try another time or another stylist?"
        
        # Add AI response to conversation
        ai_message = {"role": "assistant", "content": ai_text}
        call_data["conversation_history"].append(ai_message)
        
        # Pro: Staff transfer - AI may respond with TRANSFER_TO: Name
        transfer_name = parse_transfer_to(ai_text)
        if transfer_name:
            staff_phone = get_staff_phone_by_name(transfer_name)
            if staff_phone:
                print(f"🔄 Transferring to staff: {transfer_name} -> {staff_phone}")
                call_data["outcome"] = "forwarded"
                call_log_set_outcome(call_sid, "forwarded")
                response_status[call_sid] = {
                    "status": "forward",
                    "audio_url": None,
                    "ai_text": ai_text,
                    "forwarding_phone": staff_phone
                }
                return
        
        # Check if user wants to talk to a real person - forward if needed
        if should_forward_to_human("", ai_text):  # Check AI response for forwarding intent
            print(f"🔄 Forwarding call to business phone: {get_business_info().get('forwarding_phone')}")
            forwarding_phone = get_business_info().get("forwarding_phone")
            if forwarding_phone:
                call_data["outcome"] = "forwarded"
                call_log_set_outcome(call_sid, "forwarded")
                response_status[call_sid] = {
                    "status": "forward",
                    "audio_url": None,
                    "ai_text": ai_text,
                    "forwarding_phone": forwarding_phone
                }
                return
        
        # Generate TTS audio URL
        ai_text_encoded = quote(ai_text)
        tts_audio_url = f"{base_url}/api/phone/tts-audio?text={ai_text_encoded}&voice={get_tts_voice()}"
        
        # Mark as ready
        response_status[call_sid] = {
            "status": "ready",
            "audio_url": tts_audio_url,
            "ai_text": ai_text
        }
        print(f"✅ Response ready for call {call_sid}")
        
    except Exception as e:
        print(f"❌ Error generating response for call {call_sid}: {e}")
        import traceback
        traceback.print_exc()
        # Graceful fallback: play fallback message so caller does not get dead air
        fallback_encoded = quote(TTS_FALLBACK_TEXT)
        fallback_tts_url = f"{base_url}/api/phone/tts-audio?text={fallback_encoded}&voice={get_tts_voice()}"
        response_status[call_sid] = {
            "status": "ready",
            "audio_url": fallback_tts_url,
            "ai_text": TTS_FALLBACK_TEXT,
            "error": str(e)
        }
        print(f"⚠️ Using fallback message for call {call_sid}")

def should_forward_to_human(user_input: str, ai_response: str) -> bool:
    """
    Detect if the user wants to talk to a real person or if we should forward the call.
    Checks both user input and AI response for forwarding signals.
    """
    if not user_input:
        return False
    
    user_lower = user_input.lower()
    ai_lower = ai_response.lower() if ai_response else ""
    
    # Keywords that indicate user wants to talk to a person
    forward_keywords = [
        "talk to a person",
        "speak to someone",
        "talk to someone",
        "real person",
        "human",
        "agent",
        "representative",
        "transfer me",
        "connect me",
        "forward me",
        "can i speak to",
        "i want to speak to",
        "let me talk to",
        "put me through",
        "i need to talk to",
        "operator",
        "manager",
        "supervisor"
    ]
    
    # Check user input
    for keyword in forward_keywords:
        if keyword in user_lower:
            print(f"🔄 Forwarding requested: User said '{keyword}'")
            return True
    
    # Check AI response for forwarding signals (AI might detect intent)
    if "transfer" in ai_lower and ("you" in ai_lower or "connect" in ai_lower):
        print(f"🔄 Forwarding requested: AI detected transfer intent")
        return True
    
    return False

def forward_call_to_business(forwarding_phone: str, base_url: str, detected_lang: str = "English") -> VoiceResponse:
    """
    Forward the call to the business's actual phone number using Twilio Dial.
    """
    response = VoiceResponse()
    
    # Get language-appropriate message
    if detected_lang == "Spanish":
        message = "Conectándote con alguien ahora. Por favor espera."
    elif detected_lang == "French":
        message = "Je vous connecte maintenant. Veuillez patienter."
    else:
        message = "Connecting you with someone now. Please hold."
    
    # Say message before forwarding
    message_encoded = quote(message)
    tts_url = f"{base_url}/api/phone/tts-audio?text={message_encoded}&voice={get_tts_voice()}"
    response.play(tts_url)
    
    # Dial the business phone number
    # Format: +1XXXXXXXXXX (E.164 format)
    # Remove any non-digit characters except +
    clean_phone = ''.join(c for c in forwarding_phone if c.isdigit() or c == '+')
    if not clean_phone.startswith('+'):
        # If no +, assume US number and add +1
        if len(clean_phone) == 10:
            clean_phone = f"+1{clean_phone}"
        elif len(clean_phone) == 11 and clean_phone.startswith('1'):
            clean_phone = f"+{clean_phone}"
        else:
            clean_phone = f"+1{clean_phone}"
    
    print(f"📞 Forwarding call to business: {clean_phone}")
    response.dial(clean_phone, timeout=30, record=False)
    
    # If dial fails (no answer, busy, etc.), say goodbye
    response.say("I'm sorry, no one is available right now. Please try again later or leave a message.", voice='alice')
    response.hangup()
    
    return response

def detect_language(text: str) -> str:
    """
    Detect the language of the input text using OpenAI's intelligence.
    Returns language name in English (e.g., 'Spanish', 'Punjabi', 'English', 'French', etc.).
    This function is called on EVERY speech input to support dynamic language switching.
    Relies on OpenAI to detect any language automatically - no hardcoded word lists.
    """
    if not text or len(text.strip()) < 3:
        return "English"
    
    # Use OpenAI to detect language - it can detect any language automatically
    try:
        # Check if client is available
        if 'client' not in globals() or client is None:
            return "English"
        
        # Use OpenAI to intelligently detect the language
        # This works for any language, not just hardcoded ones
        detection_prompt = f"""Detect the language of this text and respond with ONLY the language name in English (e.g., 'Spanish', 'Punjabi', 'English', 'French', 'German', 'Chinese', 'Hindi', 'Italian', 'Portuguese', 'Japanese', 'Korean', 'Arabic', 'Russian', etc.). 

Text: {text[:200]}

Respond with just the language name, nothing else."""
        
        detection_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": detection_prompt}],
            max_tokens=15,
            temperature=0  # Low temperature for consistent language detection
        )
        detected_lang = detection_response.choices[0].message.content.strip()
        
        # Clean up response (remove quotes, extra words, periods)
        detected_lang = detected_lang.replace('"', '').replace("'", "").replace('.', '').strip()
        
        # Extract just the language name (in case GPT adds extra text)
        # Take the first word which should be the language name
        detected_lang = detected_lang.split()[0] if detected_lang.split() else detected_lang
        
        # Capitalize first letter (e.g., "spanish" -> "Spanish")
        if detected_lang:
            detected_lang = detected_lang.capitalize()
        
        if detected_lang and len(detected_lang) < 30:  # Sanity check
            return detected_lang
    except Exception as e:
        print(f"Language detection error: {e}")
        import traceback
        traceback.print_exc()
    
    # Default to English if detection fails
    return "English"

def get_system_prompt(detected_language: str = "English", caller_memory: Optional[dict] = None, include_booked_slots: bool = False):
    # Ultra-concise prompt for fastest processing while maintaining peppy, warm tone
    # CRITICAL: Respond ONLY in the detected language (language can change mid-conversation)
    services_list = ', '.join(get_business_info().get('services', []))
    specials_list = ' | '.join(get_business_info().get('specials', []))
    reservation_info = ' | '.join(get_business_info().get('reservation_rules', []))
    staff = get_business_info().get("staff") or []
    staff_block = ""
    if staff:
        staff_names = [s.get("name", "") for s in staff if s.get("name")]
        staff_block = f"\n- Staff you can transfer to: {', '.join(staff_names)}. When the caller asks to speak to one of these people by name, reply with EXACTLY: TRANSFER_TO: [Name] (use the exact name from the list). Otherwise do not use TRANSFER_TO."
    memory_block = ""
    if caller_memory and isinstance(caller_memory, dict):
        name = caller_memory.get("name") or "there"
        count = caller_memory.get("call_count", 0)
        last = caller_memory.get("last_reason") or "general inquiry"
        memory_block = f"\n- This is a REPEAT CALLER. Greet them warmly; you may say welcome back. Name if we have it: {name}. They have called {count} time(s) before; last time: {last}."
    slots_block = ""
    if include_booked_slots:
        slots_text = get_booked_slots_prompt_text()
        if slots_text:
            slots_block = f"\n- {slots_text}"
        slots_block += "\n- When the caller has confirmed a booking (you have their name, phone, date, time, and service/reason) and the slot is available, reply with EXACTLY one line: BOOKING: name|phone|email|date|time|reason (use | as separator; date YYYY-MM-DD, time HH:MM; omit optional email if unknown). Do not output BOOKING until the caller has confirmed. If a requested time is taken, suggest another time or another stylist."
    
    base_prompt = f"""Super peppy, warm AI receptionist for {get_business_info()['name']}! Be EXTRA POSITIVE and ENTHUSIASTIC! Use peppy phrases like "absolutely!", "wonderful!", "awesome!". Keep responses to 1 sentence max. Be warm, brief, and make callers feel amazing! 

You can help with:
- Hours: {get_business_info()['hours']}
- Location: {get_business_info().get('address', 'N/A')}
- Services: {services_list}
- Specials: {specials_list}
- Reservations: {reservation_info}
- Menu: Available at {get_business_info().get('menu_link', 'our website')}
- Routing to: {', '.join(get_business_info().get('departments', []))}{staff_block}{memory_block}{slots_block}"""
    
    if detected_language != "English":
        return f"""{base_prompt} CRITICAL INSTRUCTION: The caller is currently speaking in {detected_language}. You MUST respond ONLY in {detected_language}. Do NOT respond in English or any other language. Every word of your response must be in {detected_language}. If the caller switches languages, adapt immediately and respond in their new language."""
    else:
        return f"""{base_prompt} IMPORTANT: Respond in English. If the caller switches to another language, detect it and respond in that language immediately."""

@app.get("/")
async def root():
    return {"message": "Nuvatra Voice API", "status": "running"}

@app.get("/api/health")
async def health():
    """Health check for load balancers and monitoring. Returns 200 with status and DB reachability."""
    db_ok = "ok" if (USE_DB and db_ping()) else ("error" if USE_DB else "n/a")
    return {"status": "ok", "database": db_ok}

def _verify_cron_secret(request: Request) -> bool:
    """Constant-time comparison of X-Cron-Secret. Returns True if valid."""
    expected = (os.getenv("CRON_SECRET") or "").strip()
    if not expected:
        logger.warning("CRON_SECRET not set; cron auth disabled")
        return False
    received = request.headers.get("X-Cron-Secret", "")
    return hmac.compare_digest(expected.encode(), received.encode()) if received else False

@app.post("/api/cron/appointment-reminders")
async def cron_appointment_reminders(request: Request):
    """Day-before SMS reminders for accepted appointments. Requires X-Cron-Secret. Idempotent."""
    if not _verify_cron_secret(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not USE_DB:
        return {"ok": True, "reminders_sent": 0, "errors": 0, "skipped": 0, "tenants_processed": 0}
    tz_name = (os.getenv("REMINDER_TIMEZONE") or "UTC").strip()
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    tomorrow_local = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")
    reminders_sent = 0
    errors = 0
    skipped = 0
    tenants_processed = 0
    tenants = db_tenant_list_all()
    for t in tenants:
        limits = get_plan_limits(t) if get_plan_limits else {}
        if not limits.get("has_reminders"):
            continue
        tenants_processed += 1
        cid = t.get("client_id")
        twilio_num = t.get("twilio_phone_number")
        if not cid or not twilio_num:
            continue
        appointments = db_appointments_get_accepted_for_date(cid, tomorrow_local)
        for apt in appointments:
            apt_id = apt.get("id")
            phone = apt.get("phone")
            if not phone:
                skipped += 1
                continue
            if not db_appointments_mark_reminder_sent(apt_id, cid):
                skipped += 1
                continue
            cfg = load_client_config(cid)
            business_name = (cfg.get("business_name") or cfg.get("name") or "us") if cfg else "us"
            time_str = apt.get("time", "")
            body = f"Reminder: You have an appointment tomorrow at {time_str} at {business_name}. Reply YES to confirm or if you need to reschedule."
            ok = False
            for attempt in range(3):
                try:
                    set_request_client_id(cid)
                    if send_sms(phone, body, from_override=twilio_num):
                        ok = True
                        reminders_sent += 1
                        break
                except Exception as e:
                    logger.error("reminder_sms_failed", extra={"client_id": cid, "appointment_id": apt_id, "error": str(e)})
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            if not ok:
                errors += 1
    return {"ok": True, "reminders_sent": reminders_sent, "errors": errors, "skipped": skipped, "tenants_processed": tenants_processed}

@app.post("/api/cron/process-overage")
async def cron_process_overage(request: Request):
    """Monthly overage billing. Compute overage for previous month and create Stripe invoice items. Requires X-Cron-Secret."""
    if not _verify_cron_secret(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not USE_DB or not STRIPE_AVAILABLE or not stripe:
        return {"ok": True, "tenants_processed": 0, "invoices_created": 0, "errors": 0}
    price_per_min = float((os.getenv("OVERAGE_PRICE_PER_MINUTE") or "0.05").strip())
    prev_month = (datetime.now(timezone.utc) - timedelta(days=28)).strftime("%Y-%m")
    tenants_processed = 0
    invoices_created = 0
    errors = 0
    secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        return {"ok": True, "tenants_processed": 0, "invoices_created": 0, "errors": 1}
    stripe.api_key = secret
    tenants = db_tenant_list_all()
    for t in tenants:
        if t.get("subscription_status") != "active" or not t.get("stripe_customer_id"):
            continue
        cid = t.get("client_id")
        if not cid:
            continue
        if db_overage_processed_exists(cid, prev_month):
            continue
        limits = get_plan_limits(t) if get_plan_limits else {}
        cap = limits.get("minutes_cap", 999999)
        usage = db_usage_get(cid, prev_month)
        voice_minutes = usage.get("voice_minutes") or 0
        overage = max(0, voice_minutes - cap)
        if overage <= 0:
            db_overage_processed_insert(cid, prev_month)
            tenants_processed += 1
            continue
        try:
            amount_cents = int(overage * price_per_min * 100)
            if amount_cents <= 0:
                continue
            stripe.InvoiceItem.create(
                customer=t["stripe_customer_id"],
                amount=amount_cents,
                currency="usd",
                description=f"Extra minutes ({prev_month})",
            )
            db_overage_processed_insert(cid, prev_month)
            invoices_created += 1
        except Exception as e:
            logger.error("overage_invoice_failed", extra={"client_id": cid, "month": prev_month, "error": str(e)})
            errors += 1
        tenants_processed += 1
    return {"ok": True, "tenants_processed": tenants_processed, "invoices_created": invoices_created, "errors": errors}

class AdminCreateTenantRequest(BaseModel):
    client_id: str
    name: str
    twilio_phone_number: str
    email: str
    plan: Optional[str] = "starter"

@app.get("/api/debug/cors")
async def debug_cors():
    """No-auth endpoint to verify CORS config on deployed backend. e.g. curl https://your-api/api/debug/cors"""
    return {"allowed_origins": allowed_origins}

@app.post("/api/admin/tenants")
async def admin_create_tenant(req: AdminCreateTenantRequest, request: Request, admin_user_id: str = Depends(require_admin)):
    """Create tenant and send Clerk invite. Requires admin auth."""
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required for multi-tenant")
    # New tenants get 7-day trial (plan=free, subscription_status=trialing); no paid plan at creation
    tenant = db_tenant_create(req.client_id, req.name, req.twilio_phone_number, "free")
    if not tenant:
        raise HTTPException(status_code=409, detail="Tenant already exists or create failed")
    # Create config with only admin-provided info; client fills the rest in Settings
    client_dir = PROJECT_ROOT / "clients" / req.client_id
    client_dir.mkdir(parents=True, exist_ok=True)
    config_path = client_dir / "config.json"
    cfg = {
        "client_id": req.client_id,
        "business_name": req.name,
        "phone": req.twilio_phone_number or "",
        "plan": "free",
        "hours": "",
        "forwarding_phone": "",
        "email": "",
        "address": "",
        "departments": [],
        "services": [],
        "specials": [],
        "reservation_rules": [],
        "menu_link": "",
        "greeting": "",
        "staff": [],
        "locations": [],
        "voice": "fable",
        "speed": 1.0,
        "receptionist_name": "",
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    # Link the user to this tenant via Clerk.
    # If the user already has a Clerk account (e.g. re-adding a previously removed client),
    # update their metadata and add them to tenant_members directly.
    # If the user is new, send a Clerk invitation.
    clerk_secret = os.getenv("CLERK_SECRET_KEY", "").strip()
    invite_sent = False
    user_relinked = False
    if clerk_secret:
        import httpx
        headers = {"Authorization": f"Bearer {clerk_secret}", "Content-Type": "application/json"}
        # Check if user already exists in Clerk
        existing_user_id = None
        try:
            users_resp = httpx.get(
                f"https://api.clerk.com/v1/users?email_address={req.email}",
                headers=headers,
                timeout=10.0,
            )
            if users_resp.status_code < 400:
                users = users_resp.json()
                user_list = users if isinstance(users, list) else users.get("data", [])
                if user_list:
                    existing_user_id = user_list[0]["id"]
        except Exception as e:
            print(f"[Admin] Error looking up Clerk user: {e}")

        if existing_user_id:
            # User already exists — re-link them directly
            try:
                httpx.patch(
                    f"https://api.clerk.com/v1/users/{existing_user_id}",
                    headers=headers,
                    json={"public_metadata": {"tenant_id": tenant["id"]}},
                    timeout=10.0,
                )
                db_tenant_member_add(existing_user_id, tenant["id"])
                user_relinked = True
                print(f"[Admin] Re-linked existing user {existing_user_id} to tenant {tenant['id']}")
            except Exception as e:
                print(f"[Admin] Error re-linking user: {e}")
        else:
            # New user — send Clerk invitation
            try:
                resp = httpx.post(
                    "https://api.clerk.com/v1/invitations",
                    headers=headers,
                    json={
                        "email_address": req.email,
                        "public_metadata": {"tenant_id": tenant["id"]},
                        "redirect_url": os.getenv("FRONTEND_URL", "https://nuvatrahq.com") + "/",
                    },
                    timeout=10.0,
                )
                if resp.status_code >= 400:
                    print(f"[Admin] Clerk invite failed: {resp.status_code} {resp.text}")
                else:
                    invite_sent = True
            except Exception as e:
                print(f"[Admin] Clerk invite error: {e}")
    audit_log("admin", "tenant_created", actor_id=admin_user_id, resource_type="tenant", resource_id=tenant["id"], client_id=tenant["client_id"], details={"name": req.name}, request=request)
    return {"success": True, "tenant": tenant, "invite_sent": invite_sent, "user_relinked": user_relinked}

@app.get("/api/admin/tenants")
async def admin_list_tenants(_: str = Depends(require_admin)):
    """List all tenants. Requires admin auth."""
    if not USE_DB:
        return {"tenants": []}
    return {"tenants": db_tenant_list_all()}

@app.delete("/api/admin/tenants/{tenant_id}")
async def admin_delete_tenant(tenant_id: str, request: Request, admin_user_id: str = Depends(require_admin)):
    """Delete a tenant and revoke access for its members.

    Steps:
      1. Look up all tenant_members (clerk_user_ids) before cascade-delete.
      2. Delete the tenant row (cascades to tenant_members).
      3. For each former member via Clerk API:
         a. Clear tenant_id from the user's public_metadata so stale tokens
            no longer resolve to a tenant.
         b. Revoke all active sessions so the user is signed out immediately.
      Users are NOT banned — they can be re-invited to a new tenant later.
    """
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required")
    tenant = db_tenant_get_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    member_ids = db_tenant_get_members(tenant_id)
    deleted = db_tenant_delete(tenant_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete tenant")
    revoked_users: list[str] = []
    clerk_secret = os.getenv("CLERK_SECRET_KEY", "").strip()
    if clerk_secret and member_ids:
        import httpx
        headers = {"Authorization": f"Bearer {clerk_secret}", "Content-Type": "application/json"}
        for uid in member_ids:
            try:
                httpx.patch(
                    f"https://api.clerk.com/v1/users/{uid}",
                    headers=headers,
                    json={"public_metadata": {"tenant_id": None}},
                    timeout=10.0,
                )
                sessions_resp = httpx.get(
                    f"https://api.clerk.com/v1/sessions?user_id={uid}&status=active",
                    headers=headers,
                    timeout=10.0,
                )
                if sessions_resp.status_code < 400:
                    for session in sessions_resp.json().get("data", []):
                        httpx.post(
                            f"https://api.clerk.com/v1/sessions/{session['id']}/revoke",
                            headers=headers,
                            timeout=10.0,
                        )
                revoked_users.append(uid)
            except Exception as e:
                print(f"[Admin] Error revoking access for Clerk user {uid}: {e}")
    audit_log("admin", "tenant_deleted", actor_id=admin_user_id, resource_type="tenant", resource_id=tenant_id, client_id=tenant.get("client_id"), details={"name": tenant.get("name")}, request=request)
    return {"success": True, "deleted_tenant": tenant, "revoked_users": revoked_users}

class BillingExemptUpdate(BaseModel):
    exempt_until: Optional[str] = None
    extend_months: Optional[int] = None
    extend_trial_months: Optional[int] = None

@app.patch("/api/admin/tenants/{tenant_id}/billing-exempt")
async def admin_tenant_billing_exempt(tenant_id: str, req: BillingExemptUpdate, request: Request, admin_user_id: str = Depends(require_admin)):
    """Set billing exemption or extend trial for a tenant. Admin only."""
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required")
    tenant = db_tenant_get_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    now = datetime.now(timezone.utc)
    if req.extend_trial_months is not None and req.extend_trial_months >= 0:
        trial_ends_at = tenant.get("trial_ends_at")
        try:
            if trial_ends_at:
                trial_dt = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00")) if isinstance(trial_ends_at, str) else trial_ends_at
                if trial_dt.tzinfo is None:
                    trial_dt = trial_dt.replace(tzinfo=timezone.utc)
                base = max(trial_dt, now)
            else:
                base = now
            new_ends = base + timedelta(days=30 * req.extend_trial_months)
            if db_tenant_extend_trial(tenant_id, new_ends):
                audit_log("admin", "billing_exempt", actor_id=admin_user_id, resource_type="tenant", resource_id=tenant_id, client_id=tenant.get("client_id"), details={"action": "extend_trial_months", "months": req.extend_trial_months, "trial_ends_at": new_ends.isoformat()}, request=request)
                return {"success": True, "trial_ends_at": new_ends.isoformat()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    if req.extend_months is not None and req.extend_months >= 0:
        exempt_until = now + timedelta(days=30 * req.extend_months)
        if db_tenant_set_billing_exempt(tenant_id, exempt_until):
            audit_log("admin", "billing_exempt", actor_id=admin_user_id, resource_type="tenant", resource_id=tenant_id, client_id=tenant.get("client_id"), details={"action": "extend_months", "months": req.extend_months, "exempt_until": exempt_until.isoformat()}, request=request)
            return {"success": True, "billing_exempt_until": exempt_until.isoformat()}
    if req.exempt_until:
        try:
            exempt_dt = datetime.fromisoformat(req.exempt_until.replace("Z", "+00:00"))
            if exempt_dt.tzinfo is None:
                exempt_dt = exempt_dt.replace(tzinfo=timezone.utc)
            if db_tenant_set_billing_exempt(tenant_id, exempt_dt):
                audit_log("admin", "billing_exempt", actor_id=admin_user_id, resource_type="tenant", resource_id=tenant_id, client_id=tenant.get("client_id"), details={"action": "exempt_until", "exempt_until": exempt_dt.isoformat()}, request=request)
                return {"success": True, "billing_exempt_until": exempt_dt.isoformat()}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid exempt_until date: {e}")
    raise HTTPException(status_code=400, detail="Provide exempt_until, extend_months, or extend_trial_months")

@app.post("/api/admin/tenants/{tenant_id}/members")
async def admin_add_tenant_member(tenant_id: str, request: Request, email: str = Form(...), admin_user_id: str = Depends(require_admin)):
    """Manually add a Clerk user to a tenant by linking after sign-up. Use Clerk invite for new users."""
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required")
    tenant = db_tenant_get_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    audit_log("admin", "tenant_member_add_attempt", actor_id=admin_user_id, resource_type="tenant", resource_id=tenant_id, client_id=tenant.get("client_id"), details={"email": email}, request=request)
    # We would need Clerk API to look up user_id by email - skip for now; invite flow is primary
    return {"success": False, "message": "Use Clerk Invitations for new users; metadata links tenant"}

@app.post("/api/conversation", response_model=ConversationResponse)
async def handle_conversation(request: ConversationRequest, _: None = Depends(require_active_subscription)):
    try:
        # Booking context: include booked slots in prompt when user is discussing booking
        include_slots = _suggests_booking(request.message)
        if request.conversation_history:
            for m in request.conversation_history:
                if m.get("role") == "user" and _suggests_booking(m.get("content") or ""):
                    include_slots = True
                    break
        system_content = get_system_prompt(include_booked_slots=include_slots)
        messages = [{"role": "system", "content": system_content}]
        if request.conversation_history:
            messages.extend(request.conversation_history)
        messages.append({"role": "user", "content": request.message})
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.7,
            max_tokens=200
        )
        
        ai_response = response.choices[0].message.content
        action = None
        data = None
        
        # BOOKING: create appointment from AI output if present
        booking = parse_booking(ai_response)
        if booking:
            apt = _create_appointment_from_booking(booking)
            if apt:
                ai_response = f"You're all set! We have you down for {apt['date']} at {apt['time']}. The store will confirm shortly."
                action = "schedule_appointment"
                data = {"appointment_id": apt["id"]}
            else:
                ai_response = "That time slot just got booked. Would you like to try another time or another stylist?"
        
        if "schedule" in request.message.lower() or "appointment" in request.message.lower():
            action = action or "schedule_appointment"
        elif "message" in request.message.lower() or "leave a message" in request.message.lower():
            action = "take_message"
        elif "transfer" in request.message.lower() or "department" in request.message.lower():
            action = "route_call"
        
        return ConversationResponse(
            response=ai_response,
            action=action,
            data=data
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/appointments")
async def create_appointment(appointment: AppointmentRequest, _: None = Depends(require_active_subscription)):
    try:
        source = (appointment.source or "manual").strip().lower()
        if source not in ("receptionist", "manual"):
            source = "manual"
        status = "pending_review" if source == "receptionist" else "pending"
        date = (appointment.date or "").strip()
        time = (appointment.time or "").strip()
        if date and time:
            if not is_slot_available(date, time):
                raise HTTPException(status_code=409, detail="That time slot is already booked.")
        appointment_data = {
            "name": appointment.name,
            "email": appointment.email or "",
            "phone": appointment.phone or "",
            "date": date,
            "time": time,
            "reason": appointment.reason or "",
            "source": source,
            "status": status,
        }
        if USE_DB:
            row = db_appointments_insert(appointment_data)
            appointment_id = row["id"]
        else:
            appointment_id = len(appointments) + 1
            appointment_data["id"] = appointment_id
            appointment_data["created_at"] = datetime.now().isoformat()
            appointments.append(appointment_data)
        if date and time:
            reserve_slot(date, time, appointment_id)
        appointment_data["id"] = appointment_id
        appointment_data.setdefault("created_at", datetime.now().isoformat())
        return {"success": True, "appointment": appointment_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/appointments")
async def get_appointments(_: None = Depends(require_active_subscription)):
    lst = db_appointments_get_all() if USE_DB else appointments
    for a in lst:
        a.setdefault("source", "manual")
        a.setdefault("status", "pending")
    return {"appointments": lst}

@app.patch("/api/appointments/{appointment_id}")
async def update_appointment(appointment_id: int, update: AppointmentUpdate, _: None = Depends(require_active_subscription)):
    """Update appointment status or details. Used by the appointments frontend."""
    kwargs = {}
    if update.status is not None: kwargs["status"] = update.status
    if update.date is not None: kwargs["date"] = update.date
    if update.time is not None: kwargs["time"] = update.time
    if update.reason is not None: kwargs["reason"] = update.reason
    if update.name is not None: kwargs["name"] = update.name
    if update.email is not None: kwargs["email"] = update.email
    if update.phone is not None: kwargs["phone"] = update.phone
    if USE_DB and kwargs:
        apt = db_appointments_update(appointment_id, **kwargs)
        if apt:
            return {"success": True, "appointment": apt}
    else:
        for i, apt in enumerate(appointments):
            if apt["id"] == appointment_id:
                apt.update(kwargs)
                return {"success": True, "appointment": apt}
    raise HTTPException(status_code=404, detail="Appointment not found")

@app.post("/api/appointments/{appointment_id}/accept")
async def accept_appointment(appointment_id: int, request: Request, _: None = Depends(require_active_subscription)):
    """Store accepted: mark appointment accepted and send confirmation SMS to customer."""
    apt = db_appointments_get_by_id(appointment_id) if USE_DB else next((a for a in appointments if a["id"] == appointment_id), None)
    if not apt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if USE_DB:
        apt = db_appointments_update(appointment_id, status="accepted") or apt
    else:
        apt["status"] = "accepted"
    audit_log("user", "appointment_accepted", resource_type="appointment", resource_id=str(appointment_id), details={"date": apt.get("date"), "time": apt.get("time")}, request=request)
    business_name = get_business_info().get("name", "us")
    date = apt.get("date", "")
    time = apt.get("time", "")
    msg = f"Your appointment at {business_name} is confirmed for {date} at {time}. Reply if you need to change."
    send_sms(apt.get("phone") or "", msg)
    return {"success": True, "appointment": apt}

@app.post("/api/appointments/{appointment_id}/reject")
async def reject_appointment(appointment_id: int, request: Request, _: None = Depends(require_active_subscription)):
    """Store rejected (time not available): release slot and send SMS asking for alternative times."""
    apt = db_appointments_get_by_id(appointment_id) if USE_DB else next((a for a in appointments if a["id"] == appointment_id), None)
    if not apt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if USE_DB:
        apt = db_appointments_update(appointment_id, status="rejected") or apt
    else:
        apt["status"] = "rejected"
    audit_log("user", "appointment_rejected", resource_type="appointment", resource_id=str(appointment_id), details={"date": apt.get("date"), "time": apt.get("time")}, request=request)
    release_slot(appointment_id)
    date = apt.get("date", "")
    time = apt.get("time", "")
    msg = f"Sorry, {time} on {date} isn't available. Please reply with 2-3 alternative dates and times that work for you."
    send_sms(apt.get("phone") or "", msg)
    return {"success": True, "appointment": apt}

@app.post("/api/messages")
async def create_message(message: MessageRequest, _: None = Depends(require_active_subscription)):
    try:
        data = {"caller_name": message.caller_name, "caller_phone": message.caller_phone, "message": message.message, "urgency": message.urgency, "status": "unread"}
        if USE_DB:
            message_data = db_messages_insert(data)
        else:
            message_data = {"id": len(messages) + 1, **data, "created_at": datetime.now().isoformat()}
            messages.append(message_data)
        return {"success": True, "message": message_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class SmsAutomationCreate(BaseModel):
    trigger: Literal["after_inquiry", "post_call"]
    template: str

class SmsAutomationUpdate(BaseModel):
    template: Optional[str] = None
    enabled: Optional[bool] = None

@app.get("/api/sms-automations")
async def get_sms_automations(_: None = Depends(require_active_subscription)):
    """List SMS automations. Growth/Pro only."""
    cid = get_db_client_id()
    if not cid or cid == "default":
        return {"automations": []}
    tenant = db_tenant_get_by_client_id(cid)
    if not tenant or not get_plan_limits or get_plan_limits(tenant).get("sms_automations_max", 0) <= 0:
        return {"automations": []}
    automations = db_sms_automations_get_all(cid)
    return {"automations": automations}

@app.post("/api/sms-automations")
async def create_sms_automation(req: SmsAutomationCreate, tenant: Optional[dict] = Depends(require_tenant), _: None = Depends(require_active_subscription)):
    """Create SMS automation. Growth: max 2, Pro: unlimited."""
    cid = get_db_client_id()
    if not cid or cid == "default":
        raise HTTPException(status_code=400, detail="No client context")
    if not tenant or not get_plan_limits:
        raise HTTPException(status_code=403, detail="Plan does not include SMS automations")
    limits = get_plan_limits(tenant)
    if limits.get("sms_automations_max", 0) <= 0:
        raise HTTPException(status_code=403, detail="Plan does not include SMS automations")
    count = db_sms_automations_count(cid)
    if count >= limits.get("sms_automations_max", 0):
        raise HTTPException(status_code=403, detail=f"Plan allows up to {limits.get('sms_automations_max')} automations")
    automation_id = db_sms_automations_insert(cid, req.trigger, req.template or "")
    if not automation_id:
        raise HTTPException(status_code=500, detail="Failed to create automation")
    return {"id": automation_id, "trigger": req.trigger, "template": req.template}

@app.patch("/api/sms-automations/{automation_id}")
async def update_sms_automation(automation_id: int, req: SmsAutomationUpdate, _: None = Depends(require_active_subscription)):
    cid = get_db_client_id()
    if not cid or cid == "default":
        raise HTTPException(status_code=400, detail="No client context")
    ok = db_sms_automations_update(automation_id, cid, template=req.template, enabled=req.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"ok": True}

@app.delete("/api/sms-automations/{automation_id}")
async def delete_sms_automation(automation_id: int, _: None = Depends(require_active_subscription)):
    cid = get_db_client_id()
    if not cid or cid == "default":
        raise HTTPException(status_code=400, detail="No client context")
    ok = db_sms_automations_delete(automation_id, cid)
    if not ok:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"ok": True}

@app.get("/api/leads")
async def get_leads(tenant: Optional[dict] = Depends(require_tenant), _: None = Depends(require_active_subscription)):
    """Get leads for the current tenant. Growth/Pro only; Starter returns empty."""
    cid = get_db_client_id()
    if not cid or cid == "default":
        return {"leads": []}
    if tenant and get_plan_limits:
        limits = get_plan_limits(tenant)
        if not limits.get("has_lead_capture"):
            return {"leads": []}
    leads = db_leads_get_all(cid, 100) if USE_DB else []
    return {"leads": leads}

@app.get("/api/messages")
async def get_messages(_: None = Depends(require_active_subscription)):
    lst = db_messages_get_all() if USE_DB else messages
    return {"messages": lst}

@app.get("/api/subscription")
async def get_subscription(tenant: Optional[dict] = Depends(require_tenant)):
    """Return subscription state, plan limits, and usage for the current tenant."""
    state = get_tenant_subscription_state(tenant)
    if get_plan_limits:
        state["limits"] = get_plan_limits(tenant)
    cid = get_db_client_id()
    if USE_DB and cid and cid != "default":
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = db_usage_get(cid, month)
        state["usage"] = {
            "voice_minutes": usage.get("voice_minutes") or 0,
            "sms_count": usage.get("sms_count") or 0,
            "month": month,
        }
    else:
        state["usage"] = {"voice_minutes": 0, "sms_count": 0, "month": datetime.now(timezone.utc).strftime("%Y-%m")}
    return state

# ---------- Stripe billing ----------
def _stripe_price_id(plan: str) -> Optional[str]:
    key = f"STRIPE_{plan.upper()}_PRICE_ID"
    return (os.getenv(key) or os.getenv("STRIPE_PRICE_ID") or "").strip() or None

class CreateCheckoutSessionRequest(BaseModel):
    plan: Literal["starter", "growth", "pro"]

@app.post("/api/create-checkout-session")
async def create_checkout_session(req: CreateCheckoutSessionRequest, tenant: Optional[dict] = Depends(require_tenant)):
    """Create a Stripe Checkout session for the given plan. Returns { url } for redirect."""
    if not STRIPE_AVAILABLE or not stripe:
        raise HTTPException(status_code=503, detail="Billing not configured")
    if not tenant or not USE_DB:
        raise HTTPException(status_code=403, detail="Tenant required")
    secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    stripe.api_key = secret
    price_id = _stripe_price_id(req.plan)
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Price not configured for plan: {req.plan}")
    frontend = (os.getenv("FRONTEND_URL") or "http://localhost:3000").strip().rstrip("/")
    success_url = f"{frontend}/dashboard?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend}/dashboard"
    tenant_id = tenant.get("id")
    stripe_customer_id = tenant.get("stripe_customer_id")
    if not stripe_customer_id:
        try:
            cust = stripe.Customer.create(
                metadata={"tenant_id": str(tenant_id), "client_id": tenant.get("client_id", "")},
                email=None,
            )
            stripe_customer_id = cust.id
            db_tenant_update_subscription(tenant_id, stripe_customer_id=stripe_customer_id)
        except Exception as e:
            logger.error("Stripe customer create failed: %s", e)
            raise HTTPException(status_code=500, detail="Could not create billing customer")
    try:
        session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tenant_id": str(tenant_id), "plan": req.plan},
            subscription_data={"metadata": {"tenant_id": str(tenant_id), "plan": req.plan}},
        )
        return {"url": session.url}
    except Exception as e:
        logger.error("Stripe checkout session failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create-portal-session")
async def create_portal_session(tenant: Optional[dict] = Depends(require_tenant)):
    """Create a Stripe Customer Portal session for managing subscription. Returns { url }."""
    if not STRIPE_AVAILABLE or not stripe:
        raise HTTPException(status_code=503, detail="Billing not configured")
    if not tenant or not USE_DB:
        raise HTTPException(status_code=403, detail="Tenant required")
    stripe_customer_id = tenant.get("stripe_customer_id")
    if not stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account. Subscribe to a plan first.")
    secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    stripe.api_key = secret
    frontend = (os.getenv("FRONTEND_URL") or "http://localhost:3000").strip().rstrip("/")
    return_url = f"{frontend}/dashboard"
    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url,
        )
        return {"url": session.url}
    except Exception as e:
        logger.error("Stripe portal session failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks: subscription and payment events. Raw body required for signature verification."""
    if not STRIPE_AVAILABLE or not stripe:
        raise HTTPException(status_code=503, detail="Billing not configured")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")
    if not USE_DB:
        return {"received": True}
    # Handle events
    if event.type == "checkout.session.completed":
        session = event.data.object
        meta = session.get("metadata") or {}
        tenant_id = meta.get("tenant_id")
        plan = meta.get("plan") or "starter"
        sub_id = session.get("subscription")
        customer_id = session.get("customer")
        if tenant_id and (sub_id or customer_id):
            db_tenant_update_subscription(tenant_id, stripe_customer_id=customer_id, stripe_subscription_id=sub_id, subscription_status="active", plan=plan)
            tenant = db_tenant_get_by_id(tenant_id)
            audit_log("stripe", "checkout.session.completed", resource_type="tenant", resource_id=tenant_id, client_id=tenant["client_id"] if tenant else None, details={"plan": plan, "subscription_id": sub_id}, request=request)
    elif event.type == "customer.subscription.updated":
        sub = event.data.object
        sub_id = sub.get("id")
        tenant_id = (sub.get("metadata") or {}).get("tenant_id")
        status = sub.get("status")
        if tenant_id and sub_id:
            plan = (sub.get("metadata") or {}).get("plan") or "starter"
            db_tenant_update_subscription(tenant_id, stripe_subscription_id=sub_id, subscription_status=status, plan=plan)
            tenant = db_tenant_get_by_id(tenant_id)
            audit_log("stripe", "customer.subscription.updated", resource_type="tenant", resource_id=tenant_id, client_id=tenant["client_id"] if tenant else None, details={"status": status, "plan": plan}, request=request)
    elif event.type == "customer.subscription.deleted":
        sub = event.data.object
        tenant_id = (sub.get("metadata") or {}).get("tenant_id")
        if tenant_id:
            tenant = db_tenant_get_by_id(tenant_id)
            db_tenant_update_subscription(tenant_id, subscription_status="canceled")
            audit_log("stripe", "customer.subscription.deleted", resource_type="tenant", resource_id=tenant_id, client_id=tenant["client_id"] if tenant else None, details={}, request=request)
    elif event.type == "invoice.payment_failed":
        inv = event.data.object
        sub_id = inv.get("subscription")
        if sub_id and USE_DB:
            tenant = db_tenant_get_by_stripe_subscription_id(sub_id)
            if tenant:
                db_tenant_update_subscription(tenant["id"], subscription_status="past_due")
                audit_log("stripe", "invoice.payment_failed", resource_type="tenant", resource_id=tenant["id"], client_id=tenant.get("client_id"), details={"subscription_id": sub_id}, request=request)
    return {"received": True}

@app.get("/api/business-info")
async def api_get_business_info(tenant: Optional[dict] = Depends(require_active_subscription)):
    info = get_business_info()
    if not info.get("phone") and tenant:
        info["phone"] = tenant.get("twilio_phone_number") or ""
    return info

class StaffMember(BaseModel):
    name: str = ""
    phone: str = ""

class BusinessInfoUpdate(BaseModel):
    name: Optional[str] = None
    hours: Optional[str] = None
    phone: Optional[str] = None
    forwarding_phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    departments: Optional[List[str]] = None
    services: Optional[List[str]] = None
    specials: Optional[List[str]] = None
    reservation_rules: Optional[List[str]] = None
    menu_link: Optional[str] = None
    greeting: Optional[str] = None
    voice: Optional[str] = None
    speed: Optional[float] = None
    receptionist_name: Optional[str] = None
    staff: Optional[List[StaffMember]] = None

@app.patch("/api/business-info")
async def api_update_business_info(update: BusinessInfoUpdate, request: Request, _: None = Depends(require_active_subscription)):
    """Update business config (store info, voice, etc.). Writes to clients/<client_id>/config.json."""
    cid = get_db_client_id()
    if not cid or cid == "default":
        raise HTTPException(status_code=400, detail="No client context")
    config_path = PROJECT_ROOT / "clients" / cid / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Client config not found")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read config: {e}")
    if update.name is not None:
        data["business_name"] = update.name
    if update.hours is not None:
        data["hours"] = update.hours
    if update.phone is not None:
        data["phone"] = update.phone
    if update.forwarding_phone is not None:
        data["forwarding_phone"] = update.forwarding_phone
    if update.email is not None:
        data["email"] = update.email
    if update.address is not None:
        data["address"] = update.address
    if update.departments is not None:
        data["departments"] = update.departments
    if update.services is not None:
        data["services"] = update.services
    if update.specials is not None:
        data["specials"] = update.specials
    if update.reservation_rules is not None:
        data["reservation_rules"] = update.reservation_rules
    if update.menu_link is not None:
        data["menu_link"] = update.menu_link
    if update.greeting is not None:
        data["greeting"] = update.greeting
    if update.voice is not None:
        data["voice"] = update.voice
    if update.speed is not None:
        data["speed"] = update.speed
    if update.receptionist_name is not None:
        data["receptionist_name"] = update.receptionist_name
    if update.staff is not None:
        tenant = db_tenant_get_by_client_id(cid)
        if tenant and get_plan_limits:
            limits = get_plan_limits(tenant)
            staff_max = limits.get("staff_max", 1)
            if len(update.staff) > staff_max:
                raise HTTPException(status_code=403, detail=f"Plan allows up to {staff_max} staff member(s). Upgrade to add more.")
        data["staff"] = [{"name": s.name or "", "phone": s.phone or ""} for s in update.staff]
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")
    audit_log("user", "business_info_updated", resource_type="config", client_id=cid, details={"fields": [k for k in update.model_dump(exclude_none=True)]}, request=request)
    return get_business_info()

@app.get("/api/stats")
async def get_stats(_: None = Depends(require_active_subscription)):
    apts = db_appointments_get_all() if USE_DB else appointments
    msgs = db_messages_get_all() if USE_DB else messages
    pending = len([a for a in apts if a.get("status") == "pending"])
    return {
        "total_appointments": len(apts),
        "total_messages": len(msgs),
        "pending_appointments": pending
    }

def _load_call_log(days: Optional[int] = None) -> List[dict]:
    """Load call log. If days set, filter by plan (DB only). Returns list of call entries (newest first)."""
    if USE_DB:
        return db_call_log_load(limit=5000, days=days)
    data_dir = get_client_data_dir()
    if not data_dir:
        return []
    path = data_dir / "call_log.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _call_log_days(tenant: Optional[dict]) -> int:
    """Return call log retention days for plan."""
    return get_plan_limits(tenant).get("call_log_days", 30) if get_plan_limits else 9999

@app.get("/api/analytics/summary")
async def get_analytics_summary(tenant: Optional[dict] = Depends(require_tenant), _: None = Depends(require_active_subscription)):
    """Pro: Peak call times, outcomes, total calls. Filtered by plan (call_log_days)."""
    days = _call_log_days(tenant)
    log = _load_call_log(days=days)
    if not log:
        return {
            "total_calls": 0,
            "by_outcome": {},
            "by_hour": {str(h): 0 for h in range(24)},
            "by_day_of_week": {str(d): 0 for d in range(7)},
            "client_id": get_db_client_id() or None,
        }
    by_outcome = {}
    by_hour = {str(h): 0 for h in range(24)}
    by_day = {str(d): 0 for d in range(7)}
    for entry in log:
        o = entry.get("outcome") or "unknown"
        by_outcome[o] = by_outcome.get(o, 0) + 1
        start_iso = entry.get("start_iso")
        if start_iso:
            try:
                dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                by_hour[str(dt.hour)] = by_hour.get(str(dt.hour), 0) + 1
                by_day[str(dt.weekday())] = by_day.get(str(dt.weekday()), 0) + 1
            except Exception:
                pass
    return {
        "total_calls": len(log),
        "by_outcome": by_outcome,
        "by_hour": by_hour,
        "by_day_of_week": by_day,
        "client_id": CLIENT_ID or None,
    }

@app.get("/api/analytics/calls")
async def get_analytics_calls(limit: int = 50, outcome: Optional[str] = None, tenant: Optional[dict] = Depends(require_tenant), _: None = Depends(require_active_subscription)):
    """Pro: Recent calls for dashboard. Filtered by plan (call_log_days). Optional filter by outcome."""
    days = _call_log_days(tenant)
    log = _load_call_log(days=days)
    if outcome:
        log = [e for e in log if (e.get("outcome") or "") == outcome]
    return {"calls": log[:limit], "client_id": get_db_client_id() or None}

@app.get("/api/analytics/export")
async def get_analytics_export(tenant: Optional[dict] = Depends(require_tenant), _: None = Depends(require_active_subscription)):
    """Export call log as CSV. Growth/Pro only."""
    if not tenant or not get_plan_limits or not get_plan_limits(tenant).get("has_export"):
        raise HTTPException(status_code=403, detail="Export is available on Growth and Pro plans")
    days = _call_log_days(tenant)
    log = _load_call_log(days=days)
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["call_sid", "from_number", "to_number", "start_iso", "end_iso", "outcome", "duration_sec", "category", "created_at"])
    for e in log:
        writer.writerow([
            e.get("call_sid", ""),
            e.get("from_number", ""),
            e.get("to_number", ""),
            e.get("start_iso", ""),
            e.get("end_iso", ""),
            e.get("outcome", ""),
            e.get("duration_sec", ""),
            e.get("category", ""),
            e.get("created_at", ""),
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=call_log.csv"},
    )

@app.post("/api/text-to-speech")
async def text_to_speech(request: TTSRequest, _: None = Depends(require_active_subscription)):
    """
    Convert text to speech using OpenAI's TTS API.
    Returns audio file as streaming response.
    Available voices: alloy, echo, fable, onyx, nova, shimmer
    """
    try:
        tts_speed = request.speed if request.speed is not None else get_tts_speed()
        tts_speed = max(0.25, min(4.0, float(tts_speed)))
        # Generate speech using OpenAI TTS HD model for maximum quality
        response = client.audio.speech.create(
            model="tts-1-hd",  # HD model for smooth, natural, human-like quality
            voice=request.voice,
            input=add_sentence_pauses(request.text),
            speed=tts_speed
        )
        
        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)
        
        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3"
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Phone call storage (in production, use a database)
active_calls = {}  # {call_sid: {session_id, conversation_history, stream_sid, client_id, ...}}

def _restore_call_context(call_sid: str) -> bool:
    """Restore request client_id from active_calls for downstream phone handlers. Returns True if found."""
    if call_sid and call_sid in active_calls:
        cid = active_calls[call_sid].get("client_id") or CLIENT_ID or "default"
        set_request_client_id(cid)
        return True
    return False

# Fallback when OpenAI/TTS fails - play this so caller does not get dead air
TTS_FALLBACK_TEXT = "We're experiencing a brief technical issue. Please try again in a moment."

# Response generation status (for 2-step flow to eliminate dead air)
response_status = {}  # {call_sid: {"status": "pending"|"ready"|"error", "audio_url": str, "ai_text": str}}



@app.get("/api/phone/greeting-audio")
async def get_greeting_audio():
    """Serve pre-generated greeting audio for instant playback"""
    global greeting_audio_cache
    print(f"🎵 Greeting audio endpoint called. Cache status: {'✅ Cached' if greeting_audio_cache else '❌ Empty'}")
    
    if greeting_audio_cache is None:
        # Fallback: generate on the fly if cache is empty
        try:
            greeting_text = get_greeting_text()
            greeting_audio = client.audio.speech.create(
                model="tts-1-hd",
                voice="fable",
                input=add_sentence_pauses(greeting_text),
                speed=get_tts_speed()
            )
            greeting_audio_cache = greeting_audio.content
            print(f"✅ Greeting audio generated on-the-fly ({len(greeting_audio_cache)} bytes)")
        except Exception as e:
            print(f"❌ Failed to generate greeting audio: {e}")
            import traceback
            traceback.print_exc()
            try:
                fallback_audio = client.audio.speech.create(
                    model="tts-1-hd",
                    voice="fable",
                    input=add_sentence_pauses(TTS_FALLBACK_TEXT),
                    speed=1.0,
                )
                greeting_audio_cache = fallback_audio.content
                print("✅ Serving fallback greeting audio")
            except Exception as e2:
                print(f"❌ Fallback greeting audio failed: {e2}")
                raise HTTPException(status_code=500, detail=f"Failed to generate greeting: {e}")
    
    print(f"🎵 Serving greeting audio ({len(greeting_audio_cache)} bytes)")
    return Response(
        content=greeting_audio_cache,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=greeting.mp3",
            "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
            "Content-Length": str(len(greeting_audio_cache))
        }
    )

@app.get("/api/phone/got-it-audio")
async def get_got_it_audio():
    """Serve pre-generated 'Got it, one moment' audio for instant playback"""
    global got_it_audio_cache
    print(f"🎵 'Got it' audio endpoint called. Cache status: {'✅ Cached' if got_it_audio_cache else '❌ Empty'}")
    
    if got_it_audio_cache is None:
        # Fallback: generate on the fly if cache is empty
        try:
            got_it_text = "Got it, one moment."
            got_it_audio = client.audio.speech.create(
                model="tts-1-hd",
                voice="fable",
                input=add_sentence_pauses(got_it_text),
                speed=get_tts_speed()
            )
            got_it_audio_cache = got_it_audio.content
            print(f"✅ 'Got it' audio generated on-the-fly ({len(got_it_audio_cache)} bytes)")
        except Exception as e:
            print(f"❌ Failed to generate 'got it' audio: {e}")
            import traceback
            traceback.print_exc()
            try:
                got_it_audio = client.audio.speech.create(
                    model="tts-1-hd",
                    voice="fable",
                    input=add_sentence_pauses(TTS_FALLBACK_TEXT),
                    speed=1.0,
                )
                got_it_audio_cache = got_it_audio.content
                print("✅ Serving fallback 'got it' audio")
            except Exception as e2:
                print(f"❌ Fallback 'got it' audio failed: {e2}")
                raise HTTPException(status_code=500, detail=f"Failed to generate 'got it' audio: {e}")
    
    print(f"🎵 Serving 'got it' audio ({len(got_it_audio_cache)} bytes)")
    return Response(
        content=got_it_audio_cache,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=got-it.mp3",
            "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
            "Content-Length": str(len(got_it_audio_cache))
        }
    )


@app.post("/api/sms/incoming")
async def handle_incoming_sms(request: Request):
    """Twilio webhook for incoming SMS. AI-powered mobile receptionist replies like a real person."""
    if not TWILIO_AVAILABLE:
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
    if not USE_DB:
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
    try:
        form_data = await request.form()
        form_dict = dict(form_data)
        if not _validate_twilio_webhook(request, form_dict):
            return Response(content="", status_code=403, media_type="application/xml")
        from_number = form_data.get("From", "").strip()
        to_number = form_data.get("To", "").strip()
        body = (form_data.get("Body", "") or "").strip()
        if not from_number or not to_number or not body:
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
        tenant = db_tenant_get_by_phone(to_number)
        if not tenant:
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
        set_request_client_id(tenant["client_id"])
        # Pre-SMS usage check: allow overage, log for billing (Option B)
        if get_plan_limits:
            limits = get_plan_limits(tenant)
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            usage = db_usage_get(tenant["client_id"], month)
            total = (usage.get("voice_minutes") or 0) + (usage.get("sms_count") or 0)
            if total >= limits.get("minutes_cap", 999999):
                audit_log("usage", "overage_exceeded", client_id=tenant["client_id"], details={"month": month, "total": total, "cap": limits.get("minutes_cap")}, request=request)
        apt = db_appointments_get_pending_by_phone(from_number) if USE_DB else None
        session = db_sms_session_get(from_number, tenant["client_id"]) if USE_DB else None
        messages = (session["messages"] if session else []) if session else []
        messages.append({"role": "user", "content": body})
        apt_info = ""
        if apt:
            apt_info = f"The customer has a PENDING appointment: Name {apt.get('name','')}, {apt.get('date','')} at {apt.get('time','')}, service: {apt.get('reason','')}."
        else:
            apt_info = "The customer does not have a pending appointment in the system."
        business_name = get_business_info().get("name", "us")
        history_str = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-10:]])
        sys_prompt = f"""You're the friendly text receptionist for {business_name}. Keep replies short (1-3 sentences), casual, like texting a friend.

{apt_info}

They just texted: "{body}"

Previous conversation:
{history_str}

Respond naturally. If they confirm it's correct, say we'll text when the business confirms. If they want changes (date, time, name, etc.), acknowledge and say we'll update it—don't make up new details. For other questions (hours, location, services), answer from your knowledge. Be warm and helpful."""

        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": body}],
            temperature=0.8,
            max_tokens=150,
        )
        reply = (resp.choices[0].message.content or "").strip()
        if reply:
            send_sms(from_number, reply, from_override=to_number)
        messages.append({"role": "assistant", "content": reply})
        db_sms_session_upsert(from_number, tenant["client_id"], messages, apt["id"] if apt else None)
        # Lead capture: when no pending appointment and plan allows, treat as inquiry
        if not apt and get_plan_limits and get_plan_limits(tenant).get("has_lead_capture"):
            body_lower = (body or "").lower().strip()
            if len(body_lower) > 5 and body_lower not in ("yes", "no", "ok", "nope", "sure", "thanks"):
                try:
                    db_leads_insert(tenant["client_id"], None, from_number, body[:500] if body else "inquiry", "sms")
                except Exception:
                    pass
                # SMS automation: after_inquiry - send template to customer
                if USE_DB:
                    automations = db_sms_automations_get_by_trigger(tenant["client_id"], "after_inquiry")
                    for auto in automations:
                        template = (auto.get("template") or "").strip()
                        if not template:
                            continue
                        cfg = load_client_config(tenant["client_id"])
                        business_name = (cfg.get("business_name") or cfg.get("name") or "us") if cfg else "us"
                        msg = template.replace("{business_name}", business_name).replace("{name}", business_name)
                        try:
                            set_request_client_id(tenant["client_id"])
                            send_sms(from_number, msg[:1600], from_override=to_number)
                        except Exception:
                            pass
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
    except Exception as e:
        logger.exception("SMS webhook error: %s", e)
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")


@app.post("/api/phone/incoming")
async def handle_incoming_call(request: Request):
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed. Install with: pip install twilio")
    """
    Twilio webhook for incoming phone calls.
    This endpoint is called when someone calls your Twilio phone number.
    """
    try:
        # Log the incoming request for debugging
        logger.info("Incoming call webhook from %s", request.client.host if request.client else "unknown")
        form_data = await request.form()
        form_dict = dict(form_data)
        if not _validate_twilio_webhook(request, form_dict):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
        call_sid = form_data.get("CallSid")
        from_number = form_data.get("From")
        to_number = form_data.get("To")
        
        logger.info("Incoming call: %s -> %s (CallSid: %s)", from_number, to_number, call_sid)
        
        # Multi-tenant: resolve tenant by To number and set request context
        tenant = db_tenant_get_by_phone(to_number or "") if USE_DB else None
        if tenant:
            set_request_client_id(tenant["client_id"])
        elif CLIENT_ID:
            set_request_client_id(CLIENT_ID)
        # Pre-call usage check: allow overage, log for billing (Option B)
        if USE_DB and tenant and get_plan_limits:
            limits = get_plan_limits(tenant)
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            usage = db_usage_get(tenant["client_id"], month)
            total = (usage.get("voice_minutes") or 0) + (usage.get("sms_count") or 0)
            if total >= limits.get("minutes_cap", 999999):
                audit_log("usage", "overage_exceeded", client_id=tenant["client_id"], details={"month": month, "total": total, "cap": limits.get("minutes_cap")}, request=request)
        
        # Pro: call log start + customer memory for repeat callers
        call_log_start(call_sid, from_number, to_number)
        caller_memory = get_caller_memory(from_number)
        
        # Create a new session for this call (store client_id for downstream handlers)
        session_id = f"phone-{call_sid}"
        client_id = tenant["client_id"] if tenant else (CLIENT_ID or "default")
        active_calls[call_sid] = {
            "session_id": session_id,
            "from_number": from_number,
            "to_number": to_number,
            "client_id": client_id,
            "conversation_history": [],
            "detected_language": None,  # Will be detected from first speech input
            "started_at": datetime.now().isoformat(),
            "caller_memory": caller_memory,
        }
        
        # Create TwiML response
        response = VoiceResponse()
        
        # Get base URL - use the ngrok URL from environment or construct from request
        # For ngrok, we need to use the public URL, not localhost
        base_url = os.getenv("NGROK_URL")
        if not base_url:
            # Fallback: try to get from request, but replace localhost with ngrok domain if present
            request_url = str(request.url)
            if "ngrok" in request_url:
                base_url = request_url.replace("/api/phone/incoming", "")
            else:
                # Default to ngrok URL format (user should set NGROK_URL env var)
                base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
        
        # Use pre-generated cached greeting audio for instant playback (no delay!)
        greeting_audio_url = f"{base_url}/api/phone/greeting-audio"
        response.play(greeting_audio_url)
        
        # Gather voice input from caller - start with English, will adapt based on detected language
        # Note: For non-Latin scripts (Japanese, Punjabi, etc.), we'll use Record + Whisper in process-speech
        gather = response.gather(
            input='speech',
            action=f"{base_url}/api/phone/process-speech",
            method='POST',
            speech_timeout='auto',
            language='en-US',  # Start with English, will be updated dynamically after first detection
            hints='appointment, schedule, message, hours, contact, help'
        )
        
        # If no input, redirect to process speech anyway
        response.redirect(f"{base_url}/api/phone/process-speech", method='POST')
        
        return Response(content=str(response), media_type="application/xml")
    
    except Exception as e:
        print(f"❌ Error handling incoming call: {e}")
        import traceback
        traceback.print_exc()
        response = VoiceResponse()
        base_url = os.getenv("NGROK_URL") or "https://gwenda-denumerable-cami.ngrok-free.dev"
        
        # On error, forward to business phone if available
        forwarding_phone = get_business_info().get("forwarding_phone")
        if forwarding_phone:
            print(f"🔄 Error on incoming call - forwarding to business phone: {forwarding_phone}")
            error_text = "I'm experiencing technical difficulties. Let me connect you with someone who can help."
            error_encoded = quote(error_text)
            tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={get_tts_voice()}"
            response.play(tts_audio_url)
            response = forward_call_to_business(forwarding_phone, base_url, "English")
            return Response(content=str(response), media_type="application/xml")
        else:
            # Fallback: just say error message if no forwarding number
            error_text = "I'm sorry, I'm having technical difficulties. Please try again later."
            error_encoded = quote(error_text)
            tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={get_tts_voice()}"
            response.play(tts_audio_url)
            response.hangup()
            return Response(content=str(response), media_type="application/xml")

@app.post("/api/phone/process-speech")
async def process_speech(request: Request):
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed. Install with: pip install twilio")
    """
    Process speech input from phone call and generate AI response.
    """
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        speech_result = form_data.get("SpeechResult", "")
        confidence = form_data.get("Confidence", "0")
        recording_url = form_data.get("RecordingUrl", "")  # Get recording URL if available
        
        print(f"🎤 Speech received: {speech_result} (confidence: {confidence})")
        
        _restore_call_context(call_sid or "")
        if not call_sid or call_sid not in active_calls:
            # Lost call session - forward to business phone if available
            response = VoiceResponse()
            base_url = os.getenv("NGROK_URL")
            if not base_url:
                request_url = str(request.url)
                if "ngrok" in request_url:
                    base_url = request_url.replace("/api/phone/process-speech", "")
                else:
                    base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
            
            forwarding_phone = get_business_info().get("forwarding_phone")
            if forwarding_phone:
                print(f"🔄 Lost call session - forwarding to business phone: {forwarding_phone}")
                response = forward_call_to_business(forwarding_phone, base_url, "English")
                return Response(content=str(response), media_type="application/xml")
            else:
                # Fallback: say error message
                response.say("I'm sorry, I lost track of our conversation. Please call back.", voice='alice')
                return Response(content=str(response), media_type="application/xml")
        
        call_data = active_calls[call_sid]
        
        # Detect language from speech input
        current_detected_lang = detect_language(speech_result)
        
        # Check confidence and detect if this is first input
        confidence_float = float(confidence) if confidence else 0.0
        previous_lang = call_data.get("detected_language")
        is_first_input = previous_lang is None
        
        # For non-Latin scripts, Twilio transcription is often poor
        # If we detect non-Latin script AND (it's the first input OR confidence is low),
        # immediately ask user to repeat using Record + Whisper for better accuracy
        if uses_non_latin_script(current_detected_lang) and (is_first_input or confidence_float < 0.5):
            print(f"🎙️ Non-Latin script detected ({current_detected_lang}) with poor transcription quality.")
            print(f"🔄 Switching to Record + Whisper for better accuracy...")
            
            # Store the detected language
            call_data["detected_language"] = current_detected_lang
            
            # Create response asking user to repeat using Record mode
            response = VoiceResponse()
            base_url = os.getenv("NGROK_URL")
            if not base_url:
                request_url = str(request.url)
                if "ngrok" in request_url:
                    base_url = request_url.replace("/api/phone/process-speech", "")
                else:
                    base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
            
            # Ask user to repeat using Record + Whisper
            prompt_text = f"I detected you're speaking in {current_detected_lang}. For better accuracy, please speak again and press pound when done."
            prompt_encoded = quote(prompt_text)
            tts_url = f"{base_url}/api/phone/tts-audio?text={prompt_encoded}&voice={get_tts_voice()}"
            response.play(tts_url)
            
            # Set up Record for Whisper transcription
            record = response.record(
                action=f"{base_url}/api/phone/process-recording",
                method='POST',
                max_length=15,
                finish_on_key='#',
                recording_status_callback=f"{base_url}/api/phone/recording-status"
            )
            
            return Response(content=str(response), media_type="application/xml")
        
        # For languages with non-Latin scripts but good confidence on subsequent inputs
        if uses_non_latin_script(current_detected_lang):
            print(f"⚠️ Non-Latin script detected ({current_detected_lang}). Using transcription but will switch to Record + Whisper next.")
        
        # Check confidence - if very low, the transcription might be poor
        if confidence_float < 0.3:
            print(f"⚠️ Low confidence ({confidence}) - transcription may be inaccurate")

        # Always detect language from current speech input to support dynamic language switching
        # This allows the AI to adapt whenever the caller switches languages, no matter how many times
        # (e.g., if someone hands the phone to another person who speaks a different language,
        # or if the same person switches between languages)
        previous_lang = call_data.get("detected_language")
        
        # Always use the currently detected language (not stored one) to ensure real-time switching
        # Update stored language whenever it changes (supports unlimited language switches)
        if previous_lang != current_detected_lang:
            if previous_lang:
                print(f"🌍 Language switched: {previous_lang} -> {current_detected_lang} from text: {speech_result[:50]}")
            else:
                print(f"🌍 Detected language: {current_detected_lang} from text: {speech_result[:50]}")
            call_data["detected_language"] = current_detected_lang
        else:
            print(f"🌍 Using language: {current_detected_lang} (unchanged)")
        
        # Always use the freshly detected language (not the stored one) to ensure immediate switching
        detected_lang = current_detected_lang
        
        # Get base URL for TTS and forwarding
        base_url = os.getenv("NGROK_URL")
        if not base_url:
            request_url = str(request.url)
            if "ngrok" in request_url:
                base_url = request_url.replace("/api/phone/process-speech", "")
            else:
                base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
        
        # Add user message to conversation
        user_message = {
            "role": "user",
            "content": speech_result
        }
        call_data["conversation_history"].append(user_message)
        
        # Check if user wants to talk to a real person - check BEFORE generating response
        # We'll check the speech directly for forwarding keywords
        if should_forward_to_human(speech_result, ""):  # Pass empty string since we don't have AI response yet
            print(f"🔄 Forwarding call to business phone: {get_business_info().get('forwarding_phone')}")
            forwarding_phone = get_business_info().get("forwarding_phone")
            if forwarding_phone:
                call_data["outcome"] = "forwarded"
                call_log_set_outcome(call_sid, "forwarded")
                response = forward_call_to_business(forwarding_phone, base_url, detected_lang)
                return Response(content=str(response), media_type="application/xml")
        
        # Initialize response status as pending
        response_status[call_sid] = {
            "status": "pending",
            "audio_url": None,
            "ai_text": None
        }
        
        # Start background task to generate GPT response + TTS
        asyncio.create_task(generate_response_async(call_sid, call_data, detected_lang, base_url))
        
        # Immediately return "got it" message and redirect to respond endpoint
        # This eliminates dead air - caller hears something right away
        # Use pre-cached audio for instant playback (no TTS generation delay)
        response = VoiceResponse()
        got_it_audio_url = f"{base_url}/api/phone/got-it-audio"
        response.play(got_it_audio_url)
        response.redirect(f"{base_url}/api/phone/respond?CallSid={call_sid}", method='POST')
        
        return Response(content=str(response), media_type="application/xml")
        
        # Use the same base_url for next input - set language dynamically based on detected language
        # For non-Latin scripts, we'll use Record + Whisper for better accuracy
        twilio_lang_code = get_twilio_language_code(detected_lang)
        print(f"🌍 Setting Twilio language to: {twilio_lang_code} (for {detected_lang})")
        
        # For non-Latin scripts, use Record + Whisper instead of Gather for better transcription
        if uses_non_latin_script(detected_lang):
            print(f"🎙️ Using Record + Whisper for {detected_lang} (non-Latin script)")
            # Use Record verb to get audio, then transcribe with Whisper
            record = response.record(
                action=f"{base_url}/api/phone/process-recording",
                method='POST',
                max_length=10,  # 10 seconds max
                finish_on_key='#',
                recording_status_callback=f"{base_url}/api/phone/recording-status"
            )
            # Add a prompt to let user know to speak
            response.say("Please speak now, then press pound when done.", language='en-US')
        else:
            # For Latin scripts, use Gather (faster and works well)
            gather = response.gather(
                input='speech',
                action=f"{base_url}/api/phone/process-speech",
                method='POST',
                speech_timeout='auto',
                language=twilio_lang_code  # Set language dynamically for better transcription
            )
        
        # If no input, say goodbye
        response.say("Thanks for calling! Have a wonderful day!", voice='alice')
        response.hangup()
        
        return Response(content=str(response), media_type="application/xml")
    
    except Exception as e:
        print(f"❌ Error processing speech: {e}")
        import traceback
        traceback.print_exc()
        
        # On error, offer to forward to a real person
        response = VoiceResponse()
        base_url = os.getenv("NGROK_URL")
        if not base_url:
            request_url = str(request.url)
            if "ngrok" in request_url:
                base_url = request_url.replace("/api/phone/process-speech", "")
            else:
                base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
        
        # Check if we have a forwarding number - if so, forward on error
        forwarding_phone = get_business_info().get("forwarding_phone")
        if forwarding_phone:
            print(f"🔄 Error occurred - forwarding to business phone: {forwarding_phone}")
            error_text = "I'm experiencing technical difficulties. Let me connect you with someone who can help."
            error_encoded = quote(error_text)
            tts_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={get_tts_voice()}"
            response.play(tts_url)
            response = forward_call_to_business(forwarding_phone, base_url, "English")
            return Response(content=str(response), media_type="application/xml")
        else:
            # No forwarding number - just ask to repeat
            error_text = "I'm sorry, I didn't catch that. Could you repeat?"
            error_encoded = quote(error_text)
            tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={get_tts_voice()}"
            response.play(tts_audio_url)
            response.redirect(f"{base_url}/api/phone/process-speech", method='POST')
            return Response(content=str(response), media_type="application/xml")

@app.post("/api/phone/status")
async def handle_call_status(request: Request):
    """
    Twilio webhook for call status updates (call ended, etc.)
    """
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")
        
        print(f"📞 Call status update: {call_sid} -> {call_status}")
        _restore_call_context(call_sid or "")
        
        # Clean up when call ends + Pro: persist call log and customer memory
        if call_status in ["completed", "failed", "busy", "no-answer", "canceled"]:
            # Read Twilio Duration and set in call_log_entries before call_log_end
            duration_raw = form_data.get("Duration")
            if duration_raw is not None:
                try:
                    dur = int(duration_raw)
                    if call_sid in call_log_entries and dur >= 0:
                        call_log_entries[call_sid]["duration_sec"] = dur
                except (ValueError, TypeError):
                    pass
            # Capture client_id, from_number, appointment_created, duration_sec before we delete from active_calls
            client_id_before = None
            from_number_before = None
            appointment_created = False
            if call_sid in active_calls:
                call_data_cp = active_calls[call_sid]
                client_id_before = call_data_cp.get("client_id")
                from_number_before = call_data_cp.get("from_number")
                appointment_created = call_data_cp.get("appointment_created") or False
            if not client_id_before:
                client_id_before = get_db_client_id()
            if not from_number_before and call_sid in call_log_entries:
                from_number_before = call_log_entries[call_sid].get("from_number")
            duration_sec = 0
            if call_sid in call_log_entries:
                duration_sec = call_log_entries[call_sid].get("duration_sec") or 0
            if call_sid in active_calls:
                call_data = active_calls[call_sid]
                outcome = call_data.get("outcome")
                if outcome:
                    call_log_set_outcome(call_sid, outcome)
                from_number = call_data.get("from_number")
                if from_number:
                    update_caller_memory(from_number)
                call_log_end(call_sid)
                del active_calls[call_sid]
                print(f"Cleaned up call session: {call_sid}")
            elif call_sid in call_log_entries:
                # Call was logged but not in active_calls (e.g. quick hangup)
                call_log_set_outcome(call_sid, "missed" if call_status == "completed" else call_status)
                call_log_end(call_sid)
            # Lead capture: when call ended without booking and plan allows
            if USE_DB and client_id_before and client_id_before != "default" and from_number_before and get_plan_limits:
                try:
                    tenant = db_tenant_get_by_client_id(client_id_before)
                    if tenant and get_plan_limits(tenant).get("has_lead_capture") and not appointment_created:
                        db_leads_insert(client_id_before, None, from_number_before, "inquiry", "call")
                except Exception as e:
                    logger.error("lead_capture_failed", extra={"client_id": client_id_before, "error": str(e)})
            # Record voice usage for billing (graceful degradation: log on failure, do not raise)
            if USE_DB and client_id_before and client_id_before != "default":
                try:
                    minutes = max(0, math.ceil(duration_sec / 60))
                    month = datetime.now(timezone.utc).strftime("%Y-%m")
                    if not db_usage_increment_voice(client_id_before, month, minutes):
                        logger.error("usage_increment_failed", extra={"client_id": client_id_before, "month": month, "error": "db_usage_increment_voice returned False"})
                except Exception as e:
                    logger.error("usage_increment_failed", extra={"client_id": client_id_before, "error": str(e)})
        
        return Response(content="OK", media_type="text/plain")
    
    except Exception as e:
        print(f"Error handling call status: {e}")
        return Response(content="OK", media_type="text/plain")

@app.post("/api/phone/stream")
async def handle_media_stream(request: Request):
    """
    WebSocket endpoint for Twilio Media Streams.
    This handles real-time bidirectional audio streaming.
    """
    # This is a simplified version - full implementation requires WebSocket handling
    # For production, you'd use a WebSocket library like 'websockets' or 'fastapi-websocket'
    return {"message": "Media stream endpoint - requires WebSocket implementation"}

@app.post("/api/phone/respond")
async def respond_with_audio(request: Request):
    """
    Polling endpoint that checks if response audio is ready.
    Returns audio when ready, or filler + redirect if still pending.
    """
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed")
    
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        _restore_call_context(call_sid or "")
        
        if not call_sid or call_sid not in response_status:
            # Lost response status - forward to business phone if available
            response = VoiceResponse()
            forwarding_phone = get_business_info().get("forwarding_phone")
            if forwarding_phone:
                print(f"🔄 Lost response status - forwarding to business phone: {forwarding_phone}")
                # Try to get call data for language
                call_data = active_calls.get(call_sid, {})
                detected_lang = call_data.get("detected_language", "English")
                response = forward_call_to_business(forwarding_phone, base_url, detected_lang)
                return Response(content=str(response), media_type="application/xml")
            else:
                # Fallback: return error message
                response.say("I'm sorry, I'm having technical difficulties. Please try again later.", voice='alice')
                response.hangup()
                return Response(content=str(response), media_type="application/xml")
        
        status_data = response_status[call_sid]
        status = status_data.get("status", "pending")
        
        # Get base URL
        base_url = os.getenv("NGROK_URL")
        if not base_url:
            request_url = str(request.url)
            if "ngrok" in request_url:
                base_url = request_url.replace("/api/phone/respond", "")
            else:
                base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
        
        response = VoiceResponse()
        
        if status == "ready":
            # Audio is ready - play it
            audio_url = status_data.get("audio_url")
            if audio_url:
                response.play(audio_url)
                
                # After playing, set up next input gathering
                call_data = active_calls.get(call_sid, {})
                detected_lang = call_data.get("detected_language", "English")
                twilio_lang_code = get_twilio_language_code(detected_lang)
                
                # For non-Latin scripts, use Record + Whisper
                if uses_non_latin_script(detected_lang):
                    record = response.record(
                        action=f"{base_url}/api/phone/process-recording",
                        method='POST',
                        max_length=10,
                        finish_on_key='#',
                        recording_status_callback=f"{base_url}/api/phone/recording-status"
                    )
                    response.say("Please speak now, then press pound when done.", language='en-US')
                else:
                    # For Latin scripts, use Gather
                    gather = response.gather(
                        input='speech',
                        action=f"{base_url}/api/phone/process-speech",
                        method='POST',
                        speech_timeout='auto',
                        language=twilio_lang_code
                    )
                
                # If no input, say goodbye
                response.say("Thanks for calling! Have a wonderful day!", voice='alice')
                response.hangup()
                
                # Clean up status
                if call_sid in response_status:
                    del response_status[call_sid]
                
                return Response(content=str(response), media_type="application/xml")
        
        elif status == "forward":
            # Forward to business phone
            forwarding_phone = status_data.get("forwarding_phone")
            if forwarding_phone:
                detected_lang = active_calls.get(call_sid, {}).get("detected_language", "English")
                response = forward_call_to_business(forwarding_phone, base_url, detected_lang)
                # Clean up status
                if call_sid in response_status:
                    del response_status[call_sid]
                return Response(content=str(response), media_type="application/xml")
        
        elif status == "error":
            # Error occurred - forward to business phone if available
            forwarding_phone = get_business_info().get("forwarding_phone")
            if forwarding_phone:
                print(f"🔄 Error generating response - forwarding to business phone: {forwarding_phone}")
                detected_lang = active_calls.get(call_sid, {}).get("detected_language", "English")
                response = forward_call_to_business(forwarding_phone, base_url, detected_lang)
                # Clean up status
                if call_sid in response_status:
                    del response_status[call_sid]
                return Response(content=str(response), media_type="application/xml")
            else:
                # Fallback: return error message if no forwarding number
                response.say("I'm sorry, I'm having technical difficulties. Please try again later.", voice='alice')
                response.hangup()
                # Clean up status
                if call_sid in response_status:
                    del response_status[call_sid]
                return Response(content=str(response), media_type="application/xml")
        
        else:
            # Still pending - play filler and redirect again
            # Use OpenAI TTS (Fable voice) for consistency
            filler_text = "One sec."
            filler_encoded = quote(filler_text)
            filler_audio_url = f"{base_url}/api/phone/tts-audio?text={filler_encoded}&voice={get_tts_voice()}"
            response.play(filler_audio_url)
            response.pause(length=1)
            response.redirect(f"{base_url}/api/phone/respond?CallSid={call_sid}", method='POST')
            return Response(content=str(response), media_type="application/xml")
    
    except Exception as e:
        print(f"❌ Error in respond endpoint: {e}")
        import traceback
        traceback.print_exc()
        response = VoiceResponse()
        
        # On error, forward to business phone if available
        forwarding_phone = get_business_info().get("forwarding_phone")
        if forwarding_phone:
            print(f"🔄 Error in respond endpoint - forwarding to business phone: {forwarding_phone}")
            # Try to get call data for language
            call_data = active_calls.get(call_sid, {})
            detected_lang = call_data.get("detected_language", "English")
            response = forward_call_to_business(forwarding_phone, base_url, detected_lang)
            # Clean up status
            if call_sid in response_status:
                del response_status[call_sid]
            return Response(content=str(response), media_type="application/xml")
        else:
            # Fallback: return error message if no forwarding number
            response.say("I'm sorry, I'm having technical difficulties. Please try again later.", voice='alice')
            response.hangup()
            return Response(content=str(response), media_type="application/xml")

@app.get("/api/phone/tts-audio-hd")
async def get_tts_audio_hd_for_phone(text: str, voice: str = "fable"):
    """
    Generate HD TTS audio for Twilio phone calls (ultra-smooth, no choppiness).
    Used specifically for the initial greeting to ensure perfect quality.
    """
    try:
        # Use tts-1-hd for ultra-smooth, natural speech (no choppiness)
        response = client.audio.speech.create(
            model="tts-1-hd",  # HD model for ultra-smooth, natural speech
            voice=voice,
            input=add_sentence_pauses(text),
            speed=get_tts_speed()
        )
        
        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)
        
        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Cache-Control": "no-cache"
            }
        )
    except Exception as e:
        print(f"Error generating HD TTS audio: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate HD TTS audio: {str(e)}")

@app.get("/api/phone/tts-audio")
async def get_tts_audio_for_phone(text: str, voice: str = "fable"):
    """
    Generate TTS audio for phone calls.
    This endpoint is called by Twilio to play OpenAI TTS audio.
    """
    try:
        # Use tts-1 for faster generation while maintaining quality
        # tts-1 is faster than tts-1-hd but still sounds natural and smooth
        response = client.audio.speech.create(
            model="tts-1",  # Faster generation, still high quality
            voice=voice,
            input=add_sentence_pauses(text),
            speed=get_tts_speed()
        )
        
        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)
        
        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Cache-Control": "no-cache"
            }
        )
    
    except Exception as e:
        print(f"TTS audio generation error: {e}")
        try:
            response = client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=add_sentence_pauses(TTS_FALLBACK_TEXT),
                speed=1.0,
            )
            audio_bytes = io.BytesIO(response.content)
            audio_bytes.seek(0)
            return StreamingResponse(
                audio_bytes,
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "inline; filename=speech.mp3",
                    "Cache-Control": "no-cache",
                },
            )
        except Exception as e2:
            print(f"TTS fallback also failed: {e2}")
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/phone/process-recording")
async def process_recording(request: Request):
    """
    Process audio recording from Twilio for languages with non-Latin scripts.
    Transcribes using Whisper for better accuracy.
    """
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed")
    
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        recording_url = form_data.get("RecordingUrl", "")
        _restore_call_context(call_sid or "")
        
        print(f"🎙️ Recording received: {recording_url} for call {call_sid}")
        
        if not call_sid or call_sid not in active_calls:
            response = VoiceResponse()
            response.say("I'm sorry, I lost track of our conversation. Please call back.", voice='alice')
            return Response(content=str(response), media_type="application/xml")
        
        if not recording_url:
            print("⚠️ No recording URL provided")
            response = VoiceResponse()
            response.say("I didn't receive the recording. Please try again.", voice='alice')
            response.redirect(f"{os.getenv('NGROK_URL')}/api/phone/process-speech", method='POST')
            return Response(content=str(response), media_type="application/xml")
        
        call_data = active_calls[call_sid]
        
        # Download the recording from Twilio using httpx
        # httpx is already available in the environment
        try:
            import httpx
        except ImportError:
            # Fallback if httpx not available (shouldn't happen)
            raise HTTPException(status_code=500, detail="httpx library not available")
        
        recording_response = httpx.get(
            recording_url,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=30.0
        )
        if recording_response.status_code != 200:
            print(f"❌ Failed to download recording: {recording_response.status_code}")
            response = VoiceResponse()
            response.say("I had trouble processing the recording. Please try again.", voice='alice')
            response.redirect(f"{os.getenv('NGROK_URL')}/api/phone/process-speech", method='POST')
            return Response(content=str(response), media_type="application/xml")
        
        # Transcribe with Whisper
        audio_data = recording_response.content
        temp_file = io.BytesIO(audio_data)
        temp_file.name = "recording.wav"
        
        print(f"🔊 Transcribing with Whisper...")
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=temp_file
            # language parameter omitted to allow auto-detection
        )
        
        speech_result = transcript.text
        print(f"✅ Whisper transcription: {speech_result}")
        
        # Now process the transcription the same way as regular speech
        # Reuse the process_speech logic
        current_detected_lang = detect_language(speech_result)
        previous_lang = call_data.get("detected_language")
        
        if previous_lang != current_detected_lang:
            if previous_lang:
                print(f"🌍 Language switched: {previous_lang} -> {current_detected_lang}")
            else:
                print(f"🌍 Detected language: {current_detected_lang}")
            call_data["detected_language"] = current_detected_lang
        
        detected_lang = current_detected_lang
        
        # Add user message to conversation
        user_message = {
            "role": "user",
            "content": speech_result
        }
        call_data["conversation_history"].append(user_message)
        
        # Get AI response
        messages = [
            {"role": "system", "content": get_system_prompt(detected_lang)}
        ]
        messages.extend(call_data["conversation_history"])
        
        ai_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.8,
            max_tokens=80,
            stream=False
        )
        
        ai_text = ai_response.choices[0].message.content
        
        # Add AI response to conversation
        ai_message = {
            "role": "assistant",
            "content": ai_text
        }
        call_data["conversation_history"].append(ai_message)
        
        # Create TwiML response
        response = VoiceResponse()
        
        base_url = os.getenv("NGROK_URL")
        if not base_url:
            request_url = str(request.url)
            if "ngrok" in request_url:
                base_url = request_url.replace("/api/phone/process-recording", "")
            else:
                base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
        
        # Generate audio URL for AI response
        ai_text_encoded = quote(ai_text)
        tts_audio_url = f"{base_url}/api/phone/tts-audio?text={ai_text_encoded}&voice={get_tts_voice()}"
        response.play(tts_audio_url)
        
        # Set up next input based on language
        twilio_lang_code = get_twilio_language_code(detected_lang)
        
        if uses_non_latin_script(detected_lang):
            # Continue using Record + Whisper for non-Latin scripts
            record = response.record(
                action=f"{base_url}/api/phone/process-recording",
                method='POST',
                max_length=10,
                finish_on_key='#'
            )
            response.say("Please speak now, then press pound when done.", language='en-US')
        else:
            # Switch back to Gather for Latin scripts
            gather = response.gather(
                input='speech',
                action=f"{base_url}/api/phone/process-speech",
                method='POST',
                speech_timeout='auto',
                language=twilio_lang_code
            )
        
        return Response(content=str(response), media_type="application/xml")
    
    except Exception as e:
        print(f"❌ Error processing recording: {e}")
        import traceback
        traceback.print_exc()
        response = VoiceResponse()
        base_url = os.getenv("NGROK_URL") or "https://gwenda-denumerable-cami.ngrok-free.dev"
        
        # On error, forward to business phone if available
        forwarding_phone = get_business_info().get("forwarding_phone")
        if forwarding_phone:
            print(f"🔄 Error processing recording - forwarding to business phone: {forwarding_phone}")
            # Try to get call data for language
            call_data = active_calls.get(call_sid, {})
            detected_lang = call_data.get("detected_language", "English")
            response = forward_call_to_business(forwarding_phone, base_url, detected_lang)
            return Response(content=str(response), media_type="application/xml")
        else:
            # Fallback: ask to try again if no forwarding number
            response.say("I'm sorry, I had trouble processing that. Please try again.", voice='alice')
            response.redirect(f"{base_url}/api/phone/process-speech", method='POST')
            return Response(content=str(response), media_type="application/xml")

@app.post("/api/phone/recording-status")
async def recording_status(request: Request):
    """Handle recording status updates from Twilio"""
    # This endpoint can be used for logging or additional processing
    form_data = await request.form()
    print(f"📹 Recording status: {form_data.get('RecordingStatus')}")
    return Response(content="OK", media_type="text/plain")

@app.post("/api/phone/transcribe")
async def transcribe_phone_audio(audio_data: str = Form(...)):
    """
    Transcribe audio from phone call using OpenAI Whisper.
    This endpoint receives base64-encoded audio from Twilio.
    """
    try:
        # Decode base64 audio
        audio_bytes = base64.b64decode(audio_data)
        
        # Save to temporary file
        temp_file = io.BytesIO(audio_bytes)
        temp_file.name = "audio.webm"
        
        # Transcribe using OpenAI Whisper - auto-detect language for multi-language support
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=temp_file
            # language parameter omitted to allow auto-detection of any language
        )
        
        return {"transcript": transcript.text}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/phone/calls")
async def get_active_calls():
    """Get list of active phone calls"""
    return {
        "active_calls": len(active_calls),
        "calls": [
            {
                "call_sid": sid,
                "from": call_data["from_number"],
                "to": call_data["to_number"],
                "started_at": call_data["started_at"]
            }
            for sid, call_data in active_calls.items()
        ]
    }

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("Starting Nuvatra Voice Backend Server")
    print("="*50)
    print(f"Server will run on: http://0.0.0.0:8000")
    print(f"Local access: http://localhost:8000")
    print("="*50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

