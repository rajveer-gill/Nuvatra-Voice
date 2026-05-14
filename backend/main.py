import sys

from fastapi import FastAPI, HTTPException, Request, Form, Depends, WebSocket
from contextlib import asynccontextmanager
import asyncio
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError, field_validator
from typing import Optional, List, Literal, Any
import uuid
import logging
import openai
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

logger = logging.getLogger("nuvatra")
import os
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import hmac
import secrets
import math
import time
import json
import re
from pathlib import Path
import shutil
import io
from urllib.parse import quote, urlparse
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

from prompts.receptionist import build_system_prompt
from settings import get_settings
from security.webhooks import validate_twilio_webhook as validate_twilio_signature, verify_stripe_event
from security.redaction import mask_phone_e164

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

from observability import (
    auth_warning,
    sms_debug,
    sms_info,
    sms_trace,
    system_debug,
    system_info,
    usage_warning,
    voice_debug,
    voice_info,
    webhook_timing_middleware,
)


def _public_base_url() -> str:
    """HTTPS origin Twilio can reach for webhooks (use NGROK_URL or PUBLIC_BASE_URL)."""
    return (os.getenv("NGROK_URL") or os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")


def _derived_public_base_from_request(request: Request) -> str:
    """When PUBLIC_BASE_URL is unset, derive https://host from the inbound webhook (Render/proxies send X-Forwarded-*)."""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    if not host:
        return ""
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if proto not in ("https", "http"):
        proto = (request.url.scheme or "https").lower()
        if proto not in ("http", "https"):
            proto = "https"
    return f"{proto}://{host}".rstrip("/")


def _twilio_base_url(request: Request) -> str:
    """
    Absolute base URL for Twilio <Play>, <Gather action>, etc.
    Twilio rejects relative URLs — without this, calls end immediately on production if env base is unset.
    """
    bu = _public_base_url()
    if bu:
        return bu
    d = _derived_public_base_from_request(request)
    if d:
        return d
    try:
        ru = urlparse(str(request.url))
        if ru.hostname and "ngrok" in ru.hostname.lower():
            return f"{ru.scheme}://{ru.netloc}".rstrip("/")
    except Exception:
        pass
    return ""


def _settings_load_debug_enabled() -> bool:
    """Set SETTINGS_LOAD_DEBUG=1 on Render to log Settings API diagnostics (keys/types only, no PII)."""
    return os.getenv("SETTINGS_LOAD_DEBUG", "").strip().lower() in ("1", "true", "yes")


def _settings_load_debug_log_business_info(tenant: Optional[dict], out: dict) -> None:
    if not _settings_load_debug_enabled():
        return
    cid = (tenant or {}).get("client_id") if tenant else None
    prefix = (str(cid)[:10] + "…") if cid else "none"

    def _tn(key: str) -> str:
        v = out.get(key)
        return type(v).__name__ if v is not None else "none"

    logger.info(
        "settings_load_debug GET /api/business-info client_id_prefix=%s response_keys=%s "
        "services_ty=%s specials_ty=%s reservation_rules_ty=%s staff_ty=%s",
        prefix,
        sorted(out.keys()),
        _tn("services"),
        _tn("specials"),
        _tn("reservation_rules"),
        _tn("staff"),
    )


sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
    traces_sample_rate=1.0,
    integrations=[StarletteIntegration(), FastApiIntegration()],
)


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


_openai_pre_warm_disabled = False


async def pre_warm_openai():
    """Pre-warm OpenAI client. Greeting/got-it audio are generated per-client on first call (uses selected voice)."""
    global _openai_pre_warm_disabled
    if _openai_pre_warm_disabled:
        return
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
    except Exception as e:
        msg = str(e).lower()
        code = getattr(e, "status_code", None)
        if (
            code == 429
            or "insufficient_quota" in msg
            or ("429" in msg and "quota" in msg)
            or "rate_limit_exceeded" in msg
        ):
            _openai_pre_warm_disabled = True
            print(
                "[INFO] OpenAI pre-warm stopped: quota or billing limit (429). "
                "Resolve billing at platform.openai.com; keep-warm calls will skip until redeploy."
            )
            return
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


app = FastAPI(title="Call Surge API", lifespan=lifespan)

# CORS middleware (origins from settings + env)
try:
    allowed_origins = get_settings().cors_origins()
except Exception:
    allowed_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://nuvatrasite.netlify.app",
        "https://nuvatra-voice.vercel.app",
        "https://nuvatrahq.com",
        "https://call-surge.com",
        "https://www.call-surge.com",
    ]
    frontend_url = os.getenv("FRONTEND_URL")
    if frontend_url:
        u = frontend_url.rstrip("/")
        if u not in allowed_origins:
            allowed_origins.append(u)
        try:
            from urllib.parse import urlparse as _urlparse

            p = _urlparse(u)
            host = (p.hostname or "").lower()
            if host:
                scheme = p.scheme or "https"
                if host.startswith("www."):
                    apex = f"{scheme}://{host[4:]}"
                    if apex not in allowed_origins:
                        allowed_origins.append(apex)
                else:
                    www = f"{scheme}://www.{host}"
                    if www not in allowed_origins:
                        allowed_origins.append(www)
        except Exception:
            pass

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


@app.middleware("http")
async def observability_webhook_timing(request: Request, call_next):
    """When OBS_TRACE_WEBHOOKS=1, log /api/phone/* and /api/sms/* latency and status."""
    return await webhook_timing_middleware(request, call_next)


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
            usage_warning(
                "webhook_rate_limit",
                ip=ip,
                path=path,
                limit_per_min=WEBHOOK_RATE_LIMIT_PER_MIN,
            )
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

# Per-client cache for greeting (key (client_id, recording_on) -> bytes) and got-it (client_id -> bytes).
greeting_audio_cache: dict = {}
got_it_audio_cache: dict = {}

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


def _voice_stt_use_deepgram() -> bool:
    """Nova-2 live STT via Twilio Media Streams when env and credentials are present."""
    try:
        from voice.stt_config import voice_stt_provider, deepgram_api_key, media_stream_signing_secret
    except ImportError:
        return False
    if voice_stt_provider() != "deepgram":
        return False
    if not deepgram_api_key():
        logger.warning(
            "[VOICE] VOICE_STT_PROVIDER=deepgram but DEEPGRAM_API_KEY is unset; falling back to Twilio Gather"
        )
        return False
    if not media_stream_signing_secret():
        logger.warning(
            "[VOICE] VOICE_STT_PROVIDER=deepgram but MEDIA_STREAM_SIGNING_SECRET and TWILIO_AUTH_TOKEN "
            "are unset; cannot sign media WebSocket; falling back to Twilio Gather"
        )
        return False
    if not TWILIO_AVAILABLE or not twilio_client:
        logger.warning("[VOICE] VOICE_STT_PROVIDER=deepgram but Twilio client is unavailable")
        return False
    return True

# Project root (parent of backend) for client configs
PROJECT_ROOT = _backend_dir.parent
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()

def _call_recording_enabled() -> bool:
    return os.getenv("CALL_RECORDING_ENABLED", "").strip().lower() in ("1", "true", "yes")

def _call_summary_enabled() -> bool:
    raw = os.getenv("CALL_SUMMARY_ENABLED")
    if raw is None or not str(raw).strip():
        return _call_recording_enabled()
    return str(raw).strip().lower() in ("1", "true", "yes")

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
        db_call_log_update_recording,
        db_call_log_update_summary,
        db_call_log_get_client_id_by_call_sid,
        db_call_log_get_by_call_sid,
        db_caller_memory_get,
        db_caller_memory_upsert,
        db_booked_slots_load,
        db_booked_slots_save,
        db_tenant_get_by_phone,
        db_tenant_get_for_user,
        db_tenant_get_by_id,
        db_tenant_create,
        db_archive_purge_and_delete_tenant,
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
        db_sms_opt_out_is_blocked,
        db_sms_opt_out_set,
        db_sms_opt_out_clear,
        db_appointments_get_pending_by_phone,
        db_appointments_get_by_phone_for_sms,
        db_appointments_get_accepted_for_date,
        db_appointments_mark_reminder_sent,
        db_appointments_in_date_range,
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

ALLOWED_BUSINESS_VERTICALS = frozenset({"salon_chair"})
BUSINESS_VERTICAL_LABELS = {
    "salon_chair": "Salon, barbershop, nails & similar (chair services)",
}


def _normalize_service_entries(raw) -> List[dict]:
    """Migrate legacy string lists to structured service rows."""
    if not raw:
        return []
    out: List[dict] = []
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        for s in raw:
            sid = (s.get("id") or "").strip() or str(uuid.uuid4())
            try:
                price = float(s.get("price", 0))
            except (TypeError, ValueError):
                price = 0.0
            try:
                dm = int(s.get("duration_minutes", 30))
            except (TypeError, ValueError):
                dm = 30
            out.append(
                {
                    "id": sid,
                    "name": str(s.get("name") or "")[:200],
                    "price": max(0.0, min(price, 999999.0)),
                    "duration_minutes": max(5, min(dm, 480)),
                }
            )
        return out[:100]
    for line in raw if isinstance(raw, list) else []:
        t = str(line).strip()
        if t:
            out.append(
                {
                    "id": str(uuid.uuid4()),
                    "name": t[:200],
                    "price": 0.0,
                    "duration_minutes": 30,
                }
            )
    return out[:100]


def _normalize_special_entries(raw) -> List[dict]:
    if not raw:
        return []
    out: List[dict] = []
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        for s in raw:
            sid = (s.get("id") or "").strip() or str(uuid.uuid4())
            out.append(
                {
                    "id": sid,
                    "title": str(s.get("title") or "")[:200],
                    "description": str(s.get("description") or "")[:2000],
                    "valid_until": str(s.get("valid_until") or "")[:32],
                }
            )
        return out[:80]
    for line in raw if isinstance(raw, list) else []:
        t = str(line).strip()
        if t:
            out.append(
                {
                    "id": str(uuid.uuid4()),
                    "title": t[:200],
                    "description": "",
                    "valid_until": "",
                }
            )
    return out[:80]


def _normalize_rule_entries(raw) -> List[dict]:
    if not raw:
        return []
    out: List[dict] = []
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        for s in raw:
            sid = (s.get("id") or "").strip() or str(uuid.uuid4())
            out.append({"id": sid, "rule_text": str(s.get("rule_text") or "")[:2000]})
        return out[:100]
    for line in raw if isinstance(raw, list) else []:
        t = str(line).strip()
        if t:
            out.append({"id": str(uuid.uuid4()), "rule_text": t[:2000]})
    return out[:100]


def load_client_config(client_id: Optional[str] = None):
    """Load business config from clients/<client_id>/config.json. Uses request-scoped client_id if not passed."""
    cid = (client_id or get_db_client_id()).strip()
    if not cid:
        return None
    config_path = PROJECT_ROOT / "clients" / cid / "config.json"
    if not config_path.exists():
        # Normal on multi-tenant hosts until Settings PATCH creates the file; DB/minimal tenant fallback applies.
        logger.debug("client_config_missing path=%s client_id=%s", config_path, cid)
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Normalize to get_business_info() shape (do not merge BUSINESS_FORWARDING_PHONE — multi-tenant leak)
        forwarding = (data.get("forwarding_phone") or "")
        if not forwarding and data.get("locations"):
            forwarding = data["locations"][0].get("forwarding_phone", "")
        _departments = data.get("departments")
        if not isinstance(_departments, list):
            _departments = []
        info = {
            "name": data.get("business_name") or data.get("name") or "",
            "hours": data.get("hours", ""),
            "phone": data.get("phone", ""),
            "forwarding_phone": forwarding,
            "email": data.get("email", ""),
            "address": data.get("address", ""),
            "departments": _departments,
            "menu_link": data.get("menu_link", ""),
            "services": _normalize_service_entries(data.get("services", [])),
            "specials": _normalize_special_entries(data.get("specials", [])),
            "reservation_rules": _normalize_rule_entries(data.get("reservation_rules", [])),
            "staff": data.get("staff", []),
            "locations": data.get("locations", []),
            "greeting": data.get("greeting", ""),
            "plan": data.get("plan", "starter"),
            "voice": data.get("voice", "fable"),
            "speed": float(data.get("speed", 1.0)) if data.get("speed") is not None else 1.0,
            "receptionist_name": data.get("receptionist_name", ""),
            "business_type": data.get("business_type", ""),
        }
        print(f"Loaded client config: {cid} ({info['name']})")
        return info
    except Exception as e:
        print(f"WARNING: Failed to load client config: {e}")
        return None

# Business configuration: loaded per-request (multi-tenant) or at startup (single-tenant).
# Single-tenant / no-DB fallback only — do not put global env (e.g. BUSINESS_FORWARDING_PHONE) here
# or it will appear as every tenant’s “forwarding” in the UI when config is missing.
_DEMO_BUSINESS_INFO = {
        "name": "",
        "hours": "",
        "phone": "",
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
        "plan": "starter",
        "voice": "fable",
        "speed": 1.0,
        "receptionist_name": "",
        "business_type": "",
    }


def _minimal_business_info_from_tenant_dict(tenant: dict) -> dict:
    """Empty user-edited fields; Twilio line from tenant when no on-disk config (e.g. Render has no clients/)."""
    plan = tenant.get("plan") or "starter"
    bv = (tenant.get("business_vertical") or "salon_chair").strip()
    return {
        "name": "",
        "hours": "",
        "phone": (tenant.get("twilio_phone_number") or "").strip(),
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
        "plan": plan,
        "voice": "fable",
        "speed": 1.0,
        "receptionist_name": "",
        "business_type": "",
        "business_vertical": bv,
        "business_vertical_label": BUSINESS_VERTICAL_LABELS.get(bv, bv),
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
        cur.execute(
            "SELECT name, twilio_phone_number, plan, business_vertical FROM tenants WHERE client_id = %s",
            (cid,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        return _minimal_business_info_from_tenant_dict(
            {
                "twilio_phone_number": row[1] or "",
                "plan": row[2] or "starter",
                "business_vertical": row[3] if len(row) > 3 else "salon_chair",
            }
        )
    except Exception:
        return None


def business_info_for_dashboard(tenant: Optional[dict]) -> dict:
    """Settings / business-info API: never use _DEMO when a real tenant is authenticated."""
    if not tenant:
        tenant = {}
    cid = (tenant.get("client_id") or "").strip()
    if cid:
        cfg = load_client_config(cid)
        if cfg:
            out = dict(cfg)
            if not (out.get("phone") or "").strip():
                out["phone"] = (tenant.get("twilio_phone_number") or "").strip()
            bv = (tenant.get("business_vertical") or "salon_chair").strip()
            out["business_vertical"] = bv
            out["business_vertical_label"] = BUSINESS_VERTICAL_LABELS.get(bv, bv)
            out["business_type_admin_locked"] = True
            return out
    out = _minimal_business_info_from_tenant_dict(tenant)
    bv = (tenant.get("business_vertical") or "salon_chair").strip()
    out["business_vertical"] = bv
    out["business_vertical_label"] = BUSINESS_VERTICAL_LABELS.get(bv, bv)
    out["business_type_admin_locked"] = bool(cid)
    return out


def _default_client_config_data(client_id: str, plan: str = "free") -> dict:
    """Seed clients/<client_id>/config.json (admin create + first PATCH when file missing on disk)."""
    return {
        "client_id": client_id,
        "business_name": "",
        "phone": "",
        "plan": plan,
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
        "business_type": "",
    }


def get_business_info() -> dict:
    """Get business config for current request (multi-tenant) or env CLIENT_ID (single-tenant)."""
    cfg = load_client_config()
    if cfg:
        out = dict(cfg)
        if not out.get("phone") and USE_DB:
            cid = get_db_client_id()
            if cid:
                tenant = db_tenant_get_by_client_id(cid)
                if tenant:
                    out["phone"] = tenant.get("twilio_phone_number") or ""
    else:
        tenant_info = _default_business_info_for_tenant()
        if tenant_info:
            out = dict(tenant_info)
        else:
            out = dict(_DEMO_BUSINESS_INFO)
    if USE_DB:
        cid = get_db_client_id()
        if cid:
            t = db_tenant_get_by_client_id(cid)
            if t:
                bv = (t.get("business_vertical") or "salon_chair").strip()
                out["business_vertical"] = bv
                out["business_vertical_label"] = BUSINESS_VERTICAL_LABELS.get(bv, bv)
    return out

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

def invalidate_voice_cache(client_id: Optional[str] = None) -> None:
    """Clear per-client greeting/got-it audio cache when voice or speed changes in Settings."""
    global greeting_audio_cache, got_it_audio_cache
    if client_id:
        greeting_audio_cache.pop((client_id, True), None)
        greeting_audio_cache.pop((client_id, False), None)
        got_it_audio_cache.pop(client_id, None)
    else:
        greeting_audio_cache.clear()
        got_it_audio_cache.clear()

def get_greeting_text() -> str:
    """Greeting for phone (uses client config if set)."""
    info = get_business_info()
    raw = info.get("greeting") or "Thank you for calling. How can I help you today?"
    try:
        base = raw.format(business_name=info.get("name", "us"))
    except KeyError:
        base = raw
    if _call_recording_enabled():
        base = f"{base.strip()} This call may be recorded for quality and training."
    return base

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
    staff_id: Optional[str] = None  # stylist UUID from Settings staff list

class AppointmentUpdate(BaseModel):
    status: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    reason: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class AppointmentRejectBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class PreviewDeclineSmsBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)
    appointment_id: Optional[int] = None


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
        cid = (tenant or {}).get("client_id") if tenant else None
        usage_warning(
            "app_access_denied_subscription",
            client_id=cid,
            subscription_status=state.get("subscription_status"),
            plan=state.get("plan"),
        )
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

def _is_sms_confirmation(body: str) -> bool:
    """True if the message looks like the customer confirming their appointment (yes, looks good, etc.)."""
    if not body or len(body) > 80:
        return False
    b = body.lower().strip()
    # Whole-message exact matches
    exact = (
        "yes",
        "yep",
        "yeah",
        "confirm",
        "confirmed",
        "correct",
        "perfect",
        "great",
        "ok",
        "okay",
        "approved",
    )
    if b in exact:
        return True
    # Multi-word phrases (substring OK; still length-capped above)
    phrases = (
        "looks good",
        "look good",
        "that's right",
        "thats right",
        "all good",
        "sounds good",
        "sounds great",
        "that works for me",
        "that works",
    )
    for p in phrases:
        if p in b:
            return True
    # Single-word confirms: whole tokens only (avoids "yes" in "yesterday", "ok" in "token", "good" in "goods")
    tokens = set(re.findall(r"[a-z0-9']+", b))
    word_ok = {
        "yes",
        "yep",
        "yeah",
        "ok",
        "confirm",
        "confirmed",
        "correct",
        "perfect",
        "great",
        "approved",
        "okay",
    }
    return bool(tokens & word_ok)


def _sms_compliance_keyword(body: str) -> Optional[str]:
    """Parse CTIA-style keywords from inbound SMS body. Returns 'stop' | 'start' | 'help' or None."""
    words = (body or "").strip().upper().split()
    if not words:
        return None
    first = words[0].rstrip(".!")
    if first in ("STOP", "END", "CANCEL", "UNSUBSCRIBE", "QUIT", "STOPALL"):
        return "stop"
    if first in ("START", "UNSTOP"):
        return "start"
    if first in ("HELP", "INFO"):
        return "help"
    return None


def send_sms(
    to_phone: str,
    body: str,
    from_override: Optional[str] = None,
    *,
    force: bool = False,
) -> bool:
    """Send SMS via Twilio. from_override: use this number as From (for multi-tenant replies from business number).
    Records usage via db_usage_increment_sms when client_id is set.
    If force=True, skip per-tenant opt-out check (STOP/START/HELP confirmations only)."""
    if not TWILIO_AVAILABLE or not twilio_client:
        sms_info("outbound_skipped", reason="twilio_not_configured")
        return False
    from_num = (from_override or TWILIO_SMS_FROM or "").strip()
    if not from_num:
        sms_info(
            "outbound_skipped",
            reason="from_number_missing",
            from_override_set=bool(from_override),
            twilio_sms_from_set=bool(TWILIO_SMS_FROM),
        )
        return False
    e164 = _phone_to_e164(to_phone or "")
    if not e164:
        sms_info("outbound_skipped", reason="invalid_recipient_phone")
        return False
    if USE_DB and not force:
        cid = get_db_client_id()
        if cid and cid != "default":
            if db_sms_opt_out_is_blocked(e164, cid):
                to_masked = mask_phone_e164(e164)
                sms_info(
                    "outbound_skipped",
                    reason="recipient_opted_out",
                    client_id_prefix=cid[:12],
                    to_masked=to_masked,
                )
                return False
    to_masked = mask_phone_e164(e164)
    sms_debug(
        "outbound_attempt",
        from_num=from_num,
        to_masked=to_masked,
        body_len=len(body or ""),
        force=force,
    )
    sms_trace(
        "outbound_attempt",
        from_num=from_num,
        to_masked=to_masked,
        body_len=len(body or ""),
        force=force,
    )
    last_err = None
    for attempt in range(3):
        try:
            msg = twilio_client.messages.create(from_=from_num, to=e164, body=body)
            sid = getattr(msg, "sid", None) or getattr(msg, "id", None)
            sms_info(
                "outbound_twilio_ok",
                message_sid=sid,
                to_masked=to_masked,
                body_len=len(body or ""),
            )
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
            logger.warning(
                "[SMS] outbound_twilio_retry attempt=%s error=%s to_masked=%s",
                attempt + 1,
                e,
                to_masked,
            )
            if attempt < 2:
                import time
                time.sleep(2 ** attempt)
    sms_info("outbound_failed_after_retries", error=str(last_err), to_masked=to_masked)
    return False


def _tenant_sms_from_number() -> Optional[str]:
    """Outbound SMS From: tenant's Twilio number in DB, else business config phone (non-DB). None → send_sms uses TWILIO_SMS_FROM."""
    if USE_DB:
        cid = get_db_client_id()
        if cid and cid != "default":
            tenant = db_tenant_get_by_client_id(cid)
            if tenant:
                n = (tenant.get("twilio_phone_number") or "").strip()
                if n:
                    return n
    phone = (get_business_info().get("phone") or "").strip()
    return phone or None

def _validate_twilio_webhook(request: Request, form_data: dict) -> bool:
    """Validate X-Twilio-Signature so only Twilio can trigger webhooks."""
    return validate_twilio_signature(
        request,
        form_data,
        auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
        twilio_available=TWILIO_AVAILABLE,
    )

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
        raw = data.get(key)
        if not raw or not isinstance(raw, dict):
            return None
        base = {
            "name": raw.get("name"),
            "call_count": raw.get("call_count", 0),
            "last_call_iso": raw.get("last_call_iso"),
            "last_reason": raw.get("last_reason"),
        }
        mem = raw.get("data")
        if isinstance(mem, dict):
            for mk, mv in mem.items():
                if mv is not None and mv != "":
                    base[mk] = mv
        return base
    except Exception:
        return None

def update_caller_memory(
    phone: str,
    name: Optional[str] = None,
    last_reason: Optional[str] = None,
    increment_count: bool = True,
    data_patch: Optional[dict] = None,
):
    """Update caller memory after a call (increment count, set last call time and optional reason)."""
    if USE_DB:
        db_caller_memory_upsert(
            phone,
            name=name,
            last_reason=last_reason,
            increment_count=increment_count,
            data_patch=data_patch,
        )
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
    entry = data.setdefault(
        key,
        {"name": "", "call_count": 0, "last_call_iso": "", "last_reason": "", "data": {}},
    )
    if increment_count:
        entry["call_count"] = entry.get("call_count", 0) + 1
    entry["last_call_iso"] = datetime.now().isoformat()
    if name:
        entry["name"] = name
    if last_reason is not None:
        entry["last_reason"] = last_reason
    if data_patch:
        mem = entry.get("data") if isinstance(entry.get("data"), dict) else {}
        mem = {**mem, **data_patch}
        entry["data"] = mem
    data[key] = entry
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save caller memory: {e}")

def get_staff_phone_by_name(name: str) -> Optional[str]:
    """Return E.164 phone for staff member by name (case-insensitive match).
    Duplicate names under one tenant: deterministic first match in configured order."""
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
        "recording_sid": None,
        "recording_url": None,
        "recording_duration_sec": None,
        "recording_status": None,
        "call_summary": None,
    }

def call_log_merge_recording(call_sid: str, **kwargs) -> None:
    """Merge recording / summary fields into in-memory call log entry."""
    ent = call_log_entries.get(call_sid)
    if not ent:
        return
    for k, v in kwargs.items():
        if v is not None:
            ent[k] = v

def _file_call_log_merge_recording(call_sid: str, **kwargs) -> None:
    """Best-effort merge into clients/<id>/call_log.json when not using DB."""
    data_dir = get_client_data_dir()
    if not data_dir:
        return
    path = data_dir / "call_log.json"
    log_list: List[dict] = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                log_list = json.load(f)
        except Exception:
            return
    for e in reversed(log_list):
        if e.get("call_sid") == call_sid:
            for k, v in kwargs.items():
                if v is not None:
                    e[k] = v
            break
    else:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(log_list, f, indent=2)
    except Exception as ex:
        print(f"Failed to merge recording into file call log: {ex}")

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

# Booked slots (avoid double-book; inject into AI prompt)
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

def _staff_slot_key(sid: Optional[str]) -> str:
    s = (sid or "").strip()
    return s if s else "__unassigned__"


def _get_all_booked_slots_merged() -> List[dict]:
    """Merge booked_slots table with appointments (accepted/pending) so AI sees all taken times."""
    slots = _load_booked_slots()
    if USE_DB:
        apts = db_appointments_get_all()
        seen = {(s.get("date"), s.get("time"), _staff_slot_key(s.get("staff_id"))) for s in slots}
        for a in apts:
            if not a.get("date") or not a.get("time"):
                continue
            # pending_customer: details texted to caller; slot is not held until they SMS-confirm (see handle_incoming_sms).
            if a.get("status") in ("accepted", "confirmed", "completed", "pending", "pending_review"):
                sk = _staff_slot_key(a.get("staff_id"))
                k = (a["date"], a["time"], sk)
                if k not in seen:
                    slots.append({
                        "date": a["date"],
                        "time": a["time"],
                        "appointment_id": a.get("id", 0),
                        "duration_minutes": DEFAULT_SLOT_DURATION_MINUTES,
                        "staff_id": a.get("staff_id"),
                    })
                    seen.add(k)
    return slots

def get_booked_slots(date: str) -> List[dict]:
    """Return slots already booked for the given date (YYYY-MM-DD)."""
    slots = _get_all_booked_slots_merged()
    return [s for s in slots if s.get("date") == date]

def _time_to_minutes(t: str) -> int:
    """Parse time string (e.g. '10', '10:00', '10:00 AM') to minutes since midnight. Defensive against bad input."""
    if not t:
        return 0
    t = (t or "").strip()
    parts = t.replace("AM", "").replace("PM", "").strip().split(":")
    h = 0
    m = 0
    try:
        if parts:
            h = int("".join(c for c in parts[0] if c.isdigit()) or "0")
        if len(parts) > 1:
            m = int("".join(c for c in parts[1] if c.isdigit()) or "0")
    except (ValueError, TypeError):
        pass
    return h * 60 + m

def _normalize_time_to_hhmm(t: str) -> str:
    """Normalize time to HH:MM (e.g. '10' -> '10:00', '10:00 AM' -> '10:00')."""
    if not t or not (t or "").strip():
        return ""
    mins = _time_to_minutes(t)
    h, m = divmod(mins, 60)
    return f"{h:02d}:{m:02d}"

def _hhmm_to_ampm(hhmm: str) -> str:
    """Format HH:MM as 12-hour AM/PM (e.g. '13:00' -> '1:00 PM', '09:00' -> '9:00 AM')."""
    if not hhmm or not (hhmm or "").strip():
        return hhmm or ""
    normalized = _normalize_time_to_hhmm(hhmm.strip())
    if not normalized:
        return hhmm
    parts = normalized.split(":")
    try:
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return hhmm
    if h == 0:
        return f"12:{m:02d} AM"
    if h < 12:
        return f"{h}:{m:02d} AM"
    if h == 12:
        return f"12:{m:02d} PM"
    return f"{h - 12}:{m:02d} PM"

def _slot_overlaps(
    start_a: str, duration_a: int,
    start_b: str, duration_b: int
) -> bool:
    """True if two time windows overlap. start_* is HH:MM or flexible (10, 10:00, etc.)."""
    a_start = _time_to_minutes(start_a)
    a_end = a_start + duration_a
    b_start = _time_to_minutes(start_b)
    b_end = b_start + duration_b
    return a_start < b_end and b_start < a_end

def is_slot_available(
    date: str,
    time: str,
    duration_minutes: int = DEFAULT_SLOT_DURATION_MINUTES,
    staff_id: Optional[str] = None,
) -> bool:
    """True if no overlapping booking for this date+time and staff column."""
    want = _staff_slot_key(staff_id)
    slots = [s for s in _get_all_booked_slots_merged() if s.get("date") == date and _staff_slot_key(s.get("staff_id")) == want]
    for s in slots:
        d = s.get("duration_minutes") or DEFAULT_SLOT_DURATION_MINUTES
        if _slot_overlaps(time, duration_minutes, s.get("time", ""), d):
            system_debug(
                "slot_unavailable",
                date=date,
                time=time,
                staff_key=want,
                overlaps_time=s.get("time"),
            )
            return False
    system_debug("slot_available", date=date, time=time, staff_key=want)
    return True

def reserve_slot(
    date: str,
    time: str,
    appointment_id: int,
    duration_minutes: int = DEFAULT_SLOT_DURATION_MINUTES,
    staff_id: Optional[str] = None,
) -> None:
    """Record a slot as booked when creating an appointment."""
    slots = _load_booked_slots()
    slots.append({
        "date": date,
        "time": time,
        "appointment_id": appointment_id,
        "duration_minutes": duration_minutes,
        "staff_id": staff_id,
    })
    _save_booked_slots(slots)
    _invalidate_booked_slots_cache()
    system_debug(
        "slot_reserved",
        date=date,
        time=time,
        appointment_id=appointment_id,
        staff_id=staff_id,
    )

def release_slot(appointment_id: int) -> None:
    """Remove slot when appointment is rejected or cancelled."""
    slots = _load_booked_slots()
    slots = [s for s in slots if s.get("appointment_id") != appointment_id]
    _save_booked_slots(slots)
    _invalidate_booked_slots_cache()
    system_debug("slot_released", appointment_id=appointment_id)

# Cache for booked slots prompt (avoids repeated DB hits during rapid turns)
_booked_slots_cache: dict = {}  # {client_key: (text, expires_at)}
_BOOKED_SLOTS_CACHE_TTL_SEC = 10  # Short TTL so "available" and actual check stay in sync

def _invalidate_booked_slots_cache() -> None:
    """Clear booked slots cache so next prompt build sees current availability (e.g. after reserve/release)."""
    _booked_slots_cache.clear()

def get_booked_slots_prompt_text(days_ahead: int = 90, skip_cache: bool = False) -> str:
    """Build a short line for the system prompt: already booked slots for today + days_ahead."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    client_key = get_db_client_id() or "default"
    cache_key = f"{client_key}:{days_ahead}"
    if not skip_cache and cache_key in _booked_slots_cache:
        text, expires = _booked_slots_cache[cache_key]
        if expires > now:
            system_debug("booked_slots_prompt_cache_hit", client_key=client_key, slots_text_len=len(text))
            return text
        del _booked_slots_cache[cache_key]
    # Single merge + group by date (was: 90x get_booked_slots = 90x DB fetches)
    all_slots = _get_all_booked_slots_merged()
    system_debug(
        "booked_slots_prompt_built",
        client_key=client_key,
        skip_cache=skip_cache,
        total_slots=len(all_slots),
    )
    by_date: dict = {}
    for s in all_slots:
        dt = s.get("date")
        if not dt:
            continue
        if dt not in by_date:
            by_date[dt] = []
        t = s.get("time", "")
        if t:
            by_date[dt].append(t)
    today = now.date()
    # Common business-hour times to suggest when some slots are taken (so we never suggest a taken time)
    default_times = [f"{h:02d}:00" for h in range(9, 18)]  # 09:00–17:00
    parts = []
    suggest_parts = []
    for d in range(days_ahead):
        day = today + timedelta(days=d)
        date_str = day.isoformat()
        times = by_date.get(date_str) or []
        if times:
            # Show times in AM/PM for the AI to speak (e.g. "1:00 PM" not "13:00")
            times_display = [_hhmm_to_ampm(t) for t in sorted(times)]
            parts.append(f"{date_str} at {', '.join(times_display)}")
            # Explicit list of times the AI may suggest (exclude taken); normalize for comparison
            taken_set = {_normalize_time_to_hhmm(t.strip()) for t in times if t}
            taken_set = {t for t in taken_set if t}
            safe = [t for t in default_times if t not in taken_set]
            if safe:
                safe_display = [_hhmm_to_ampm(t) for t in safe]
                taken_display = [_hhmm_to_ampm(t) for t in sorted(taken_set)]
                suggest_parts.append(f"For {date_str} ONLY suggest these times (they are free): {', '.join(safe_display)}. Never suggest {', '.join(taken_display)}—already taken.")
    text = ("Booked slots (do not double-book): " + "; ".join(parts) + ". ") if parts else ""
    if suggest_parts:
        text += " " + " ".join(suggest_parts)
    expires_at = now + timedelta(seconds=_BOOKED_SLOTS_CACHE_TTL_SEC)
    _booked_slots_cache[cache_key] = (text, expires_at)
    return text

def _suggests_booking(text: str) -> bool:
    """True if the message suggests the caller wants to book/appointment/reservation."""
    if not text or len(text.strip()) < 2:
        return False
    t = text.lower()
    return any(k in t for k in ("book", "appointment", "reservation", "reserve", "schedule", "available", "slot", "time for"))

def parse_booking(ai_text: str) -> Optional[dict]:
    """If AI responded with BOOKING: name|phone|email|date|time|reason|staff_optional, return dict; else None.

    The marker may appear after prose on the same line or after newlines — not only at line start.
    Empty fields are allowed (e.g. name|||date|time|reason with ||| for missing phone/email).
    """
    if not ai_text or "BOOKING:" not in ai_text.upper():
        return None
    m = re.search(r"(?is)BOOKING:\s*([^\n]+)", ai_text)
    if not m:
        return None
    rest = (m.group(1) or "").strip()
    vals = [v.strip() for v in rest.split("|")]
    if len(vals) < 5:
        return None
    return {
        "name": vals[0] if len(vals) > 0 else "",
        "phone": vals[1] if len(vals) > 1 else "",
        "email": vals[2] if len(vals) > 2 else "",
        "date": vals[3] if len(vals) > 3 else "",
        "time": vals[4] if len(vals) > 4 else "",
        "reason": vals[5] if len(vals) > 5 else "",
        "staff": vals[6] if len(vals) > 6 else "",
    }


def _strip_booking_directive_for_voice(ai_text: str) -> str:
    """Remove BOOKING:... from model output so it is never read aloud by TTS."""
    if not ai_text or "BOOKING:" not in ai_text.upper():
        return (ai_text or "").strip()
    cleaned = re.sub(r"(?is)\s*BOOKING:\s*[^\n]+", "", ai_text).strip()
    return cleaned if cleaned else (ai_text or "").strip()


def resolve_staff_id_from_booking_fragment(fragment: Optional[str]) -> Optional[str]:
    frag = (fragment or "").strip()
    if not frag:
        return None
    staff = get_business_info().get("staff") or []
    for s in staff:
        sid = (s.get("id") or "").strip()
        if sid and frag == sid:
            return sid
        name = (s.get("name") or "").strip()
        if name and frag.lower() == name.lower():
            return sid if sid else None
    return None


def _optional_staff_id_validated(raw: Optional[str]) -> Optional[str]:
    """If staff_id is set, ensure it matches a row in this tenant's staff list."""
    sid = (raw or "").strip()
    if not sid:
        return None
    for s in get_business_info().get("staff") or []:
        if (s.get("id") or "").strip() == sid:
            return sid
    raise HTTPException(status_code=400, detail="Invalid staff_id for this business.")


def _create_appointment_from_booking(
    booking: dict,
    client_id_override: Optional[str] = None,
    reserve_slot_immediately: bool = True,
) -> Optional[dict]:
    """Create appointment from parsed BOOKING; check slot; return appointment_data or None (slot taken).
    Pass client_id_override from voice flow so appointment is stored under correct tenant (async task may not have context).
    When reserve_slot_immediately is False (voice), the row is created as pending_customer but the calendar slot
    is only reserved after the customer SMS-confirms (see handle_incoming_sms)."""
    date = (booking.get("date") or "").strip()
    time_raw = (booking.get("time") or "").strip()
    time = _normalize_time_to_hhmm(time_raw) or time_raw  # e.g. "10" -> "10:00"
    name = (booking.get("name") or "").strip()
    if not name or not date or not time:
        return None
    staff_key = resolve_staff_id_from_booking_fragment(booking.get("staff"))
    if not is_slot_available(date, time, DEFAULT_SLOT_DURATION_MINUTES, staff_key):
        _invalidate_booked_slots_cache()  # Next prompt build will see slot as taken
        system_info(
            "booking_create_failed_slot_taken",
            name=name,
            date=date,
            time=time,
        )
        return None
    appointment_data = {
        "name": name,
        "email": (booking.get("email") or "").strip(),
        "phone": (booking.get("phone") or "").strip(),
        "date": date,
        "time": time,
        "reason": (booking.get("reason") or "").strip() or "—",
        "source": "receptionist",
        "status": "pending_customer",
        "staff_id": staff_key,
    }
    if client_id_override:
        appointment_data["client_id"] = client_id_override
    if USE_DB:
        row = db_appointments_insert(appointment_data)
        apt_id = row["id"]
    else:
        apt_id = len(appointments) + 1
        appointment_data["id"] = apt_id
        appointment_data["created_at"] = datetime.now().isoformat()
        appointments.append(appointment_data)
    if reserve_slot_immediately:
        reserve_slot(date, time, apt_id, DEFAULT_SLOT_DURATION_MINUTES, staff_key)
    appointment_data["id"] = apt_id
    appointment_data.setdefault("created_at", datetime.now().isoformat())
    system_info(
        "booking_created_pending_customer",
        apt_id=apt_id,
        client_id=appointment_data.get("client_id") or "(request_context)",
        name=name,
        date=date,
        time=time,
        staff_id=staff_key,
        slot_reserved_immediately=reserve_slot_immediately,
    )
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
        # Keep tenant context so SMS and DB use correct client_id (async runs outside request)
        set_request_client_id(call_data.get("client_id") or get_db_client_id())
        voice_info(
            "generate_response_start",
            call_sid=call_sid,
            from_number=call_data.get("from_number") or None,
            client_id=call_data.get("client_id") or None,
        )
        
        # Always include booked slots (skip cache so prompt and is_slot_available see same data—avoids "available" then "booked")
        messages = [
            {"role": "system", "content": get_system_prompt(detected_lang, call_data.get("caller_memory"), include_booked_slots=True, skip_slots_cache=True)}
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
        voice_debug("gpt_reply", call_sid=call_sid, reply_preview=(ai_text or "")[:80])
        # BOOKING: create appointment from AI output if present; replace response with confirmation or slot-taken message
        booking = parse_booking(ai_text)
        if booking:
            try:
                from_num = call_data.get("from_number") or ""
                to_num = call_data.get("to_number") or ""
                cid_raw = call_data.get("client_id") or ""
                system_info(
                    "voice_booking_line_parsed",
                    name=booking.get("name"),
                    date=booking.get("date"),
                    time=booking.get("time"),
                    from_number=from_num or None,
                    to_number=to_num or None,
                    client_id=cid_raw or None,
                )
                # Use caller's phone from Twilio when available (don't require asking)
                if from_num:
                    booking["phone"] = (booking.get("phone") or "").strip() or from_num
                cid = (call_data.get("client_id") or "").strip() or None
                apt = _create_appointment_from_booking(
                    booking, client_id_override=cid, reserve_slot_immediately=False
                )
                if apt:
                    call_data["appointment_created"] = True
                    ai_text = (
                        "I've texted you the details. Please check your phone and reply YES or CONFIRM when everything looks right—that locks the time and sends your request to the shop. "
                        "The time is not finalized until you confirm by text."
                    )
                    # Ensure we have caller phone (backfill from Twilio if missing) so SMS goes out and dashboard shows it
                    if not (apt.get("phone") or "").strip() and call_data.get("from_number"):
                        apt["phone"] = call_data["from_number"]
                        if USE_DB and apt.get("id"):
                            try:
                                db_appointments_update(apt["id"], phone=apt["phone"])
                            except Exception:
                                pass
                    # Send caller a text: full details (name, phone, email, date, time, service) so they can confirm or request changes before we send to store
                    phone_display = (apt.get("phone") or "").strip() or "Not provided"
                    email_display = (apt.get("email") or "").strip() or "Not provided"
                    thanks_msg = (
                        f"Hey! Here's what we have for you — the time is NOT locked in until you text back YES or CONFIRM:\n"
                        f"Name: {apt.get('name', '')}\n"
                        f"Phone: {phone_display}\n"
                        f"Email: {email_display}\n"
                        f"Date: {apt.get('date', '')}\n"
                        f"Time: {_hhmm_to_ampm(apt.get('time', '') or '')}\n"
                        f"Service: {apt.get('reason', '')}\n\n"
                        f"Reply YES or CONFIRM only when this looks exactly right — that reserves the time and sends this to the store. "
                        f"You can also reply with changes.\n\n"
                        f"Msg & data rates may apply. Reply STOP to opt out."
                    )
                    # Prefer caller number from live call so confirmation SMS always goes to the right person
                    to_number = (call_data.get("from_number") or "").strip() or (apt.get("phone") or "").strip() or ""
                    from_number = (call_data.get("to_number") or "").strip() if call_data else None
                    if not from_number and cid and USE_DB:
                        tenant = db_tenant_get_by_client_id(cid)
                        if tenant:
                            from_number = (tenant.get("twilio_phone_number") or "").strip()
                            sms_info("confirmation_sms_from_tenant_lookup", client_id=cid)
                        else:
                            sms_info("confirmation_sms_tenant_missing_for_from_override", client_id=cid)
                    if to_number:
                        ok = send_sms(to_number, thanks_msg, from_override=from_number or None)
                        sms_info(
                            "post_booking_confirmation_sms",
                            client_id=cid,
                            to_number=to_number,
                            from_number=from_number,
                            success=ok,
                        )
                    else:
                        sms_info("post_booking_confirmation_skipped", reason="no_caller_phone", client_id=cid)
                    fn_mem = (call_data.get("from_number") or "").strip()
                    if fn_mem:
                        dp = {
                            "last_voice_booking_date": apt.get("date"),
                            "last_voice_booking_time": apt.get("time"),
                            "last_service": ((apt.get("reason") or "").strip()[:120] or None),
                        }
                        em_patch = (apt.get("email") or "").strip()
                        if em_patch:
                            dp["email_on_file"] = em_patch
                        dp = {k: v for k, v in dp.items() if v}
                        try:
                            update_caller_memory(
                                fn_mem,
                                name=(booking.get("name") or "").strip() or None,
                                last_reason="appointment details texted (pending SMS confirmation)",
                                increment_count=False,
                                data_patch=dp if dp else None,
                            )
                        except Exception:
                            pass
                else:
                    # Failed: either slot taken or missing/invalid data (name, date)
                    name_ok = bool((booking.get("name") or "").strip())
                    date_ok = bool((booking.get("date") or "").strip())
                    time_ok = bool((booking.get("time") or "").strip())
                    reason = "slot_taken" if (name_ok and date_ok and time_ok) else ("no_name" if not name_ok else "no_date_time")
                    system_info(
                        "voice_booking_not_created",
                        reason=reason,
                        name_ok=name_ok,
                        date_ok=date_ok,
                        time_ok=time_ok,
                    )
                    if not name_ok:
                        ai_text = "I'd love to book that for you—what's your name?"
                    elif not date_ok or not time_ok:
                        ai_text = "I need the date and time again to confirm—which day and time would you like?"
                    else:
                        ai_text = "That time slot just got booked. Would you like to try another time or another day?"
            except Exception as e:
                logger.exception("voice_booking_or_sms_failed call_sid=%s: %s", call_sid, e)
                ai_text = "We've got your request. If you don't get a confirmation text in a moment, please call back—we'll have your details."
        
        # Never send BOOKING: machine line to TTS or conversation history
        ai_text = _strip_booking_directive_for_voice(ai_text or "")
        if not ai_text:
            ai_text = "Thanks—we've noted that. Let us know if you need anything else."
        
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

def append_forward_call_verbs(
    response: VoiceResponse,
    forwarding_phone: str,
    base_url: str,
    detected_lang: str = "English",
) -> None:
    """Append handoff TTS, Dial, and no-answer fallback to an existing TwiML response."""
    if detected_lang == "Spanish":
        message = "Conectándote con alguien ahora. Por favor espera."
    elif detected_lang == "French":
        message = "Je vous connecte maintenant. Veuillez patienter."
    else:
        message = "Connecting you with someone now. Please hold."

    message_encoded = quote(message)
    tts_url = f"{base_url}/api/phone/tts-audio?text={message_encoded}&voice={get_tts_voice()}"
    response.play(tts_url)

    clean_phone = "".join(c for c in forwarding_phone if c.isdigit() or c == "+")
    if not clean_phone.startswith("+"):
        if len(clean_phone) == 10:
            clean_phone = f"+1{clean_phone}"
        elif len(clean_phone) == 11 and clean_phone.startswith("1"):
            clean_phone = f"+{clean_phone}"
        else:
            clean_phone = f"+1{clean_phone}"

    print(f"📞 Forwarding call to business: {clean_phone}")
    response.dial(clean_phone, timeout=30, record=False)
    response.say(
        "I'm sorry, no one is available right now. Please try again later or leave a message.",
        voice="alice",
    )
    response.hangup()


def forward_call_to_business(forwarding_phone: str, base_url: str, detected_lang: str = "English") -> VoiceResponse:
    """
    Forward the call to the business's actual phone number using Twilio Dial.
    """
    response = VoiceResponse()
    append_forward_call_verbs(response, forwarding_phone, base_url, detected_lang)
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

def get_system_prompt(
    detected_language: str = "English",
    caller_memory: Optional[dict] = None,
    include_booked_slots: bool = False,
    skip_slots_cache: bool = False,
):
    """Compose GPT system prompt for voice; slot lines come from live booking state."""
    info = get_business_info()
    booked_text = None
    if include_booked_slots:
        booked_text = get_booked_slots_prompt_text(skip_cache=skip_slots_cache)
    return build_system_prompt(
        business_info=info,
        detected_language=detected_language,
        caller_memory=caller_memory,
        include_booked_slots=include_booked_slots,
        booked_slots_prompt_text=booked_text,
    )

@app.get("/")
async def root():
    return {"message": "Call Surge API", "status": "running"}

@app.get("/api/health")
async def health():
    """Health check for load balancers and monitoring. Returns 200 with status and DB reachability."""
    db_ok = "ok" if (USE_DB and db_ping()) else ("error" if USE_DB else "n/a")
    return {"status": "ok", "database": db_ok}


def _sentry_debug_allowed(request: Request) -> bool:
    """Do not expose a public crash endpoint in production. Opt-in via env or shared secret header."""
    if (os.getenv("ENABLE_SENTRY_DEBUG_ROUTE") or "").strip().lower() in ("1", "true", "yes"):
        return True
    secret = (os.getenv("SENTRY_DEBUG_SECRET") or "").strip()
    if secret:
        got = (request.headers.get("X-Sentry-Debug-Secret") or "").strip()
        if not got:
            return False
        try:
            return secrets.compare_digest(secret, got)
        except Exception:
            return False
    return False


@app.get("/sentry-debug")
async def trigger_sentry_error(request: Request):
    if not _sentry_debug_allowed(request):
        raise HTTPException(status_code=404, detail="Not Found")
    _ = 1 / 0  # intentional test error for Sentry when route is enabled


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
    business_vertical: str = "salon_chair"

@app.get("/api/admin/session")
async def admin_session(request: Request):
    """True if the bearer token user id is in ADMIN_CLERK_USER_IDS. No tenant required."""
    token = get_bearer_token(request)
    if not token:
        return {"is_admin": False}
    try:
        user_id, _ = verify_clerk_token(token)
    except HTTPException:
        return {"is_admin": False}
    admin_ids = [x.strip() for x in (os.getenv("ADMIN_CLERK_USER_IDS") or "").split(",") if x.strip()]
    if not admin_ids:
        return {"is_admin": False}
    return {"is_admin": user_id in admin_ids}

@app.get("/api/debug/cors")
async def debug_cors():
    """No-auth endpoint to verify CORS config on deployed backend. e.g. curl https://your-api/api/debug/cors"""
    return {"allowed_origins": allowed_origins}

@app.post("/api/admin/tenants")
async def admin_create_tenant(req: AdminCreateTenantRequest, request: Request, admin_user_id: str = Depends(require_admin)):
    """Create tenant and send Clerk invite. Requires admin auth."""
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required for multi-tenant")
    bv = (req.business_vertical or "salon_chair").strip()
    if bv not in ALLOWED_BUSINESS_VERTICALS:
        raise HTTPException(status_code=400, detail="Invalid business_vertical")
    # New tenants get 7-day trial (plan=free, subscription_status=trialing); no paid plan at creation
    tenant = db_tenant_create(req.client_id, req.name, req.twilio_phone_number, "free", bv)
    if not tenant:
        raise HTTPException(status_code=409, detail="Tenant already exists or create failed")
    # Create config with only admin-provided info; client fills the rest in Settings
    client_dir = PROJECT_ROOT / "clients" / req.client_id
    client_dir.mkdir(parents=True, exist_ok=True)
    config_path = client_dir / "config.json"
    cfg = _default_client_config_data(req.client_id, tenant.get("plan") or "free")
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
                        "redirect_url": os.getenv("FRONTEND_URL", "https://call-surge.com") + "/",
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
      1. Look up all tenant_members (clerk_user_ids) before any destructive work.
      2. Archive all client_id-scoped operational data to tenant_removed_archive, then delete live rows
         (so a new tenant reusing the same client_id does not see old appointments, etc.; archive supports retention).
      3. Remove clients/<client_id> on-disk config if present.
      4. Delete the tenant row (cascades to tenant_members).
      5. For each former member via Clerk API: clear public_metadata tenant_id and revoke sessions.
      Users are NOT banned — they can be re-invited to a new tenant later.
    """
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required")
    tenant = db_tenant_get_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    member_ids = db_tenant_get_members(tenant_id)
    archive_id = db_archive_purge_and_delete_tenant(tenant_id, tenant, actor_clerk_id=admin_user_id)
    if archive_id is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to archive tenant operational data; tenant was not removed. Retry or check database logs.",
        )
    client_slug = (tenant.get("client_id") or "").strip()
    if client_slug:
        client_dir = PROJECT_ROOT / "clients" / client_slug
        try:
            if client_dir.is_dir():
                shutil.rmtree(client_dir, ignore_errors=True)
        except Exception as e:
            print(f"[Admin] Could not remove client directory {client_dir}: {e}")
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
    audit_log(
        "admin",
        "tenant_deleted",
        actor_id=admin_user_id,
        resource_type="tenant",
        resource_id=tenant_id,
        client_id=tenant.get("client_id"),
        details={"name": tenant.get("name"), "data_archive_id": archive_id},
        request=request,
    )
    return {"success": True, "deleted_tenant": tenant, "revoked_users": revoked_users, "data_archive_id": archive_id}

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
        # Always include booked slots so the AI knows which times are taken and avoids double-booking
        system_content = get_system_prompt(include_booked_slots=True)
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
                ai_response = f"You're all set! We have you down for {apt['date']} at {_hhmm_to_ampm(apt.get('time', '') or '')}. The store will confirm shortly."
                action = "schedule_appointment"
                data = {"appointment_id": apt["id"]}
            else:
                name_ok = bool((booking.get("name") or "").strip())
                date_ok = bool((booking.get("date") or "").strip())
                time_ok = bool((booking.get("time") or "").strip())
                if not name_ok:
                    ai_response = "I'd love to book that for you—what's your name?"
                elif not date_ok or not time_ok:
                    ai_response = "I need the date and time again to confirm—which day and time would you like?"
                else:
                    ai_response = "That time slot just got booked. Would you like to try another time or another day?"
        
        ai_response = _strip_booking_directive_for_voice(ai_response or "")
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


def polish_owner_decline_sms(raw_reason: str, business_name: str, apt: dict) -> str:
    """Rewrite owner decline note into a warm customer SMS (OpenAI). Fallback: truncate raw."""
    text = (raw_reason or "").strip()
    if not text:
        text = "We could not accommodate that time."
    try:
        _ensure_openai_client()
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write brief SMS messages for a salon, barbershop, or nail studio. "
                        "Rewrite the owner's decline reason into ONE warm, natural message. "
                        "Max 480 characters. Do not invent discounts, guarantees, or policies. "
                        "If appropriate, invite alternative dates/times. Match the tone of the owner's note."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Business name: {business_name}\n"
                        f"Appointment requested: {apt.get('date')} at {apt.get('time')}\n"
                        f"Owner note: {text[:1800]}"
                    ),
                },
            ],
            max_tokens=220,
            temperature=0.45,
        )
        out = (r.choices[0].message.content or "").strip()
        return out[:1580] if out else text[:1580]
    except Exception as e:
        logger.warning("polish_owner_decline_sms_openai_failed: %s", e)
        return text[:1580]


def _staff_pending_review_sms_enabled() -> bool:
    return (os.getenv("STAFF_PENDING_REVIEW_SMS") or "").strip().lower() in ("1", "true", "yes", "on")


def _notify_staff_pending_review(apt: dict, tenant: dict, twilio_from_number: str) -> None:
    """Optional cost-controlled SMS to each staff phone when a customer submits the booking for shop approval."""
    if not _staff_pending_review_sms_enabled():
        return
    apt_id = apt.get("id")
    if not apt_id:
        return
    cfg = load_client_config(tenant["client_id"]) or {}
    staff_list = cfg.get("staff") or []
    n_staff_phones = len([s for s in staff_list if (s.get("phone") or "").strip()])
    sms_info(
        "staff_pending_review_notify_start",
        apt_id=apt_id,
        client_id=tenant["client_id"],
        staff_sms_targets=n_staff_phones,
    )
    nm = (apt.get("name") or "").strip() or "Customer"
    ds = (apt.get("date") or "").strip()
    tm = _hhmm_to_ampm((apt.get("time") or "").strip())
    msg = (
        f"New booking request #{apt_id}: {nm}, {ds} at {tm}. "
        f"Reply YES {apt_id} to approve or NO {apt_id} plus a short reason to decline."
    )
    for s in staff_list:
        phone = (s.get("phone") or "").strip()
        if not phone:
            continue
        try:
            send_sms(phone, msg[:1580], from_override=twilio_from_number)
        except Exception as e:
            logger.warning("[SMS] staff_pending_review_notify_failed apt_id=%s err=%s", apt_id, e)


def _maybe_handle_staff_sms_approval(from_number: str, body: str, tenant: dict, to_number: str) -> bool:
    """
    If From matches a staff member's phone, parse APPROVE/YES or DECLINE/NO <apt_id> [reason].
    Returns True if this webhook turn was consumed as a staff command.
    """
    norm_from = _phone_to_e164(from_number)
    if not norm_from:
        return False
    cfg = load_client_config(tenant["client_id"]) or {}
    staff_list = cfg.get("staff") or []
    is_staff = False
    for s in staff_list:
        sp = _phone_to_e164(s.get("phone") or "")
        if sp and sp == norm_from:
            is_staff = True
            break
    if not is_staff:
        return False
    raw = (body or "").strip()
    tokens = raw.split()
    sms_trace(
        "inbound_staff_phone_matched",
        client_id=tenant["client_id"],
        body_len=len(raw),
        token_count=len(tokens),
    )
    if len(tokens) < 2:
        sms_debug("staff_command_incomplete", from_number=from_number, body_len=len(raw))
        sms_trace("inbound_staff_command_incomplete", client_id=tenant["client_id"], token_count=len(tokens))
        return False
    verb = tokens[0].upper()
    try:
        apt_id = int(tokens[1])
    except ValueError:
        sms_info("staff_command_invalid_id_token", from_number=from_number, token=str(tokens[1])[:20])
        return False
    apt = db_appointments_get_by_id(apt_id) if USE_DB else None
    if not apt:
        sms_info(
            "staff_command_unknown_appointment",
            apt_id=apt_id,
            client_id=tenant["client_id"],
            from_number=from_number,
        )
        send_sms(
            from_number,
            "We could not find that booking reference.",
            from_override=to_number,
            force=True,
        )
        return True
    if str(apt.get("status") or "") != "pending_review":
        sms_info(
            "staff_command_wrong_status",
            apt_id=apt_id,
            status=apt.get("status"),
            client_id=tenant["client_id"],
            from_number=from_number,
        )
        send_sms(
            from_number,
            "That booking is not awaiting approval.",
            from_override=to_number,
            force=True,
        )
        return True
    business_name = get_business_info().get("name", "your shop")
    if verb in ("YES", "APPROVE", "OK", "ACCEPT"):
        if USE_DB:
            db_appointments_update(apt_id, status="accepted")
        audit_log(
            "staff_sms",
            "appointment_accepted",
            resource_type="appointment",
            resource_id=str(apt_id),
            client_id=tenant["client_id"],
            details={"via": "sms"},
        )
        msg = (
            f"Your appointment at {business_name} is confirmed for {apt.get('date')} at "
            f"{_hhmm_to_ampm(apt.get('time') or '')}. Reply if you need to change."
        )
        send_sms(apt.get("phone") or "", msg, from_override=to_number)
        send_sms(
            from_number,
            f"Booking {apt_id} approved. Customer notified.",
            from_override=to_number,
            force=True,
        )
        sms_info(
            "staff_sms_approved",
            apt_id=apt_id,
            client_id=tenant["client_id"],
            from_number=from_number,
        )
        return True
    if verb in ("NO", "DECLINE", "REJECT"):
        reason = " ".join(tokens[2:]).strip() or "We could not accommodate that time."
        if USE_DB:
            db_appointments_update(apt_id, status="rejected", owner_decline_reason=reason[:2000])
        release_slot(apt_id)
        audit_log(
            "staff_sms",
            "appointment_rejected",
            resource_type="appointment",
            resource_id=str(apt_id),
            client_id=tenant["client_id"],
            details={"via": "sms"},
        )
        polished = polish_owner_decline_sms(reason, business_name, apt)
        send_sms(apt.get("phone") or "", polished, from_override=to_number)
        send_sms(
            from_number,
            "Decline sent to the customer.",
            from_override=to_number,
            force=True,
        )
        sms_info(
            "staff_sms_declined",
            apt_id=apt_id,
            client_id=tenant["client_id"],
            from_number=from_number,
        )
        return True
    return False


@app.post("/api/appointments")
async def create_appointment(appointment: AppointmentRequest, _: None = Depends(require_active_subscription)):
    try:
        source = (appointment.source or "manual").strip().lower()
        if source not in ("receptionist", "manual"):
            source = "manual"
        status = "pending_review" if source == "receptionist" else "pending"
        date = (appointment.date or "").strip()
        time = (appointment.time or "").strip()
        staff_key = _optional_staff_id_validated(appointment.staff_id)
        if date and time:
            if not is_slot_available(date, time, DEFAULT_SLOT_DURATION_MINUTES, staff_key):
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
            "staff_id": staff_key,
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
            reserve_slot(date, time, appointment_id, DEFAULT_SLOT_DURATION_MINUTES, staff_key)
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


@app.get("/api/appointments/calendar")
async def appointments_calendar(
    date_from: str,
    date_to: str,
    staff_id: Optional[str] = None,
    _: None = Depends(require_active_subscription),
):
    """Return appointments for calendar grid (optionally filtered by staff UUID)."""
    if not USE_DB:
        return {"events": []}
    events = db_appointments_in_date_range(date_from, date_to, staff_id)
    return {"events": events}


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
    if str(apt.get("status") or "") != "pending_review":
        raise HTTPException(status_code=400, detail="Appointment is not awaiting approval")
    if USE_DB:
        apt = db_appointments_update(appointment_id, status="accepted") or apt
    else:
        apt["status"] = "accepted"
    audit_log("user", "appointment_accepted", resource_type="appointment", resource_id=str(appointment_id), details={"date": apt.get("date"), "time": apt.get("time")}, request=request)
    business_name = get_business_info().get("name", "us")
    date = apt.get("date", "")
    time_ampm = _hhmm_to_ampm(apt.get("time") or "")
    msg = f"Your appointment at {business_name} is confirmed for {date} at {time_ampm}. Reply if you need to change."
    send_sms(apt.get("phone") or "", msg, from_override=_tenant_sms_from_number())
    return {"success": True, "appointment": apt}


@app.post("/api/appointments/{appointment_id}/reject")
async def reject_appointment(
    appointment_id: int,
    body: AppointmentRejectBody,
    request: Request,
    _: None = Depends(require_active_subscription),
):
    """Reject request with owner-provided reason; AI-polished SMS to customer."""
    apt = db_appointments_get_by_id(appointment_id) if USE_DB else next((a for a in appointments if a["id"] == appointment_id), None)
    if not apt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if str(apt.get("status") or "") != "pending_review":
        raise HTTPException(status_code=400, detail="Appointment is not awaiting approval")
    reason_clean = body.reason.strip()
    if USE_DB:
        apt = db_appointments_update(
            appointment_id, status="rejected", owner_decline_reason=reason_clean
        ) or apt
    else:
        apt["status"] = "rejected"
    audit_log(
        "user",
        "appointment_rejected",
        resource_type="appointment",
        resource_id=str(appointment_id),
        details={"date": apt.get("date"), "time": apt.get("time")},
        request=request,
    )
    release_slot(appointment_id)
    business_name = get_business_info().get("name", "us")
    msg = polish_owner_decline_sms(reason_clean, business_name, apt)
    send_sms(apt.get("phone") or "", msg, from_override=_tenant_sms_from_number())
    return {"success": True, "appointment": apt}


@app.post("/api/appointments/preview-decline-sms")
async def preview_decline_sms(body: PreviewDeclineSmsBody, _: None = Depends(require_active_subscription)):
    """Return AI-polished decline text without sending SMS (for owner review before reject)."""
    apt: dict = {}
    if body.appointment_id is not None and USE_DB:
        apt = db_appointments_get_by_id(body.appointment_id) or {}
        if not apt:
            raise HTTPException(status_code=404, detail="Appointment not found")
    business_name = get_business_info().get("name", "us")
    polished = polish_owner_decline_sms(body.reason.strip(), business_name, apt if apt else {"date": "", "time": ""})
    return {"polished_message": polished}


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
async def get_sms_automations(tenant: Optional[dict] = Depends(require_active_subscription)):
    """List SMS automations. Growth/Pro only."""
    cid = get_db_client_id()
    if not cid or cid == "default":
        if _settings_load_debug_enabled():
            logger.info("settings_load_debug GET /api/sms-automations early_empty cid_default=%s", not cid or cid == "default")
        return {"automations": []}
    if get_plan_limits:
        limits = get_plan_limits(tenant) if tenant else {}
        if limits.get("sms_automations_max", 0) <= 0:
            if _settings_load_debug_enabled():
                logger.info("settings_load_debug GET /api/sms-automations plan_has_no_automations_slot")
            return {"automations": []}
    automations = db_sms_automations_get_all(cid)
    if _settings_load_debug_enabled():
        logger.info(
            "settings_load_debug GET /api/sms-automations client_id_prefix=%s count=%s",
            (str(cid)[:10] + "…") if cid else "none",
            len(automations) if isinstance(automations, list) else "na",
        )
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
    if _settings_load_debug_enabled():
        cid = (tenant or {}).get("client_id") if tenant else None
        prefix = (str(cid)[:10] + "…") if cid else "none"
        logger.info(
            "settings_load_debug GET /api/subscription client_id_prefix=%s keys=%s can_use_app=%s",
            prefix,
            sorted(state.keys()) if isinstance(state, dict) else type(state).__name__,
            (state.get("can_use_app") if isinstance(state, dict) else None),
        )
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
        # Trial users may not have a Stripe customer yet; create one so they can use the portal
        secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
        if not secret:
            raise HTTPException(status_code=503, detail="Stripe not configured")
        stripe.api_key = secret
        try:
            cust = stripe.Customer.create(
                metadata={"tenant_id": str(tenant.get("id")), "client_id": tenant.get("client_id", "")},
                email=None,
            )
            stripe_customer_id = cust.id
            db_tenant_update_subscription(tenant.get("id"), stripe_customer_id=stripe_customer_id)
        except Exception as e:
            logger.error("Stripe customer create failed for portal: %s", e)
            raise HTTPException(status_code=500, detail="Could not create billing account")
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
    event, verr = verify_stripe_event(payload, sig, webhook_secret=secret, stripe_module=stripe)
    if verr:
        code = 503 if verr == "Webhook secret not configured" else 400
        raise HTTPException(status_code=code, detail=verr)
    assert event is not None
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
    out = business_info_for_dashboard(tenant)
    _settings_load_debug_log_business_info(tenant, out)
    return out

# Required and recommended fields so the AI receptionist can relay accurate info (any business type)
# Setup checklist labels must stay in sync with Settings.tsx checklist rows.
SETUP_REQUIRED_FIELDS = [
    ("name", "Business name"),
    ("hours", "Hours of operation"),
    ("forwarding_phone", "Phone number"),
    ("address", "Address"),
]

def get_setup_status(info_override: Optional[dict] = None) -> dict:
    """Return setup completeness. Uses info_override if provided (e.g. with tenant phone merged), else get_business_info()."""
    info = info_override if info_override is not None else get_business_info()
    missing: List[str] = []
    warnings: List[str] = []
    for key, label in SETUP_REQUIRED_FIELDS:
        val = info.get(key)
        if not (val and str(val).strip()):
            missing.append(label)
    services = info.get("services") or []
    departments = info.get("departments") or []
    if not (services or departments):
        warnings.append("Add services or departments so the AI knows what your business offers (e.g. appointments, estimates, emergency service)")
    return {
        "complete": len(missing) == 0,
        "missing": missing,
        "warnings": warnings,
    }

@app.get("/api/setup-status")
async def api_setup_status(tenant: Optional[dict] = Depends(require_active_subscription)):
    """Return which required/recommended business info fields are missing. Used for setup checklist."""
    info = business_info_for_dashboard(tenant)
    body = get_setup_status(info_override=info)
    if _settings_load_debug_enabled():
        cid = (tenant or {}).get("client_id") if tenant else None
        prefix = (str(cid)[:10] + "…") if cid else "none"
        logger.info(
            "settings_load_debug GET /api/setup-status client_id_prefix=%s complete=%s missing_n=%s",
            prefix,
            body.get("complete"),
            len(body.get("missing") or []),
        )
    return body


def _staff_sanitize_single_line(raw: Optional[str]) -> str:
    """Strip whitespace; disallow control chars and newlines (name, phone paths)."""
    if raw is None:
        return ""
    s = str(raw)
    s = "".join(c for c in s if ord(c) >= 32)
    return s.strip()


def _staff_sanitize_notes(raw: Optional[str]) -> str:
    """Notes: allow TAB/LF/CR; strip NUL and other C0 controls."""
    if raw is None:
        return ""
    s = "".join(c for c in str(raw) if ord(c) >= 32 or c in "\t\n\r")
    return s.strip()


class StaffMember(BaseModel):
    id: Optional[str] = Field(default=None, max_length=36)
    name: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=32)
    email: str = Field(default="", max_length=254)
    notes: str = Field(default="", max_length=4000)

    @field_validator("id", mode="before")
    @classmethod
    def strip_id_optional(cls, v):
        if v is None:
            return None
        vv = str(v).strip()
        return vv if vv else None

    @field_validator("id")
    @classmethod
    def id_must_be_uuid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            return str(uuid.UUID(v))
        except ValueError as e:
            raise ValueError("Staff id must be a valid UUID when provided.") from e

    @field_validator("name", mode="before")
    @classmethod
    def sanitize_name(cls, v):
        return _staff_sanitize_single_line(v if v is not None else "")[:120]

    @field_validator("phone", mode="before")
    @classmethod
    def sanitize_phone(cls, v):
        return _staff_sanitize_single_line(v if v is not None else "")[:32]

    @field_validator("notes", mode="before")
    @classmethod
    def sanitize_notes_field(cls, v):
        return _staff_sanitize_notes(v if v is not None else "")

    @field_validator("email", mode="before")
    @classmethod
    def sanitize_email_raw(cls, v):
        if v is None:
            return ""
        s = "".join(c for c in str(v).strip() if ord(c) >= 32)
        return s[:254]

    @field_validator("email")
    @classmethod
    def validate_email_optional(cls, v: str) -> str:
        if not v:
            return ""
        try:
            return str(TypeAdapter(EmailStr).validate_python(v))
        except ValidationError as e:
            raise ValueError("Invalid email address.") from e


def finalize_staff_records_for_storage(members: List[StaffMember]) -> List[dict]:
    """Serialize staff for config.json; assign UUID when id omitted (backward compatible rows)."""
    out: List[dict] = []
    for m in members:
        sid = (m.id or "").strip() or str(uuid.uuid4())
        out.append({
            "id": sid,
            "name": m.name,
            "phone": m.phone,
            "email": m.email,
            "notes": m.notes,
        })
    return out


class BusinessInfoUpdate(BaseModel):
    name: Optional[str] = None
    hours: Optional[str] = None
    phone: Optional[str] = None
    forwarding_phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    departments: Optional[List[str]] = None
    services: Optional[List[Any]] = None
    specials: Optional[List[Any]] = None
    reservation_rules: Optional[List[Any]] = None
    menu_link: Optional[str] = None
    greeting: Optional[str] = None
    voice: Optional[str] = None
    speed: Optional[float] = None
    receptionist_name: Optional[str] = None
    business_type: Optional[str] = None
    staff: Optional[List[StaffMember]] = None

@app.patch("/api/business-info")
async def api_update_business_info(update: BusinessInfoUpdate, request: Request, tenant: Optional[dict] = Depends(require_active_subscription)):
    """Update business config (store info, voice, etc.). Writes to clients/<client_id>/config.json."""
    tid = tenant or {}
    cid = ((tid.get("client_id") or "").strip() or get_db_client_id()).strip()
    if not cid or cid == "default":
        raise HTTPException(status_code=400, detail="No client context")
    config_path = PROJECT_ROOT / "clients" / cid / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read config: {e}")
    else:
        # Use JWT-resolved tenant (always present here); do not require DB lookup — fails when USE_DB is off or DB is down.
        plan = tid.get("plan") or "free"
        if USE_DB:
            trow = db_tenant_get_by_client_id(cid)
            if trow and trow.get("plan"):
                plan = trow.get("plan") or plan
        data = _default_client_config_data(cid, plan)
        config_path.parent.mkdir(parents=True, exist_ok=True)
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
        data["services"] = _normalize_service_entries(update.services)
    if update.specials is not None:
        data["specials"] = _normalize_special_entries(update.specials)
    if update.reservation_rules is not None:
        data["reservation_rules"] = _normalize_rule_entries(update.reservation_rules)
    if update.menu_link is not None:
        data["menu_link"] = update.menu_link
    if update.greeting is not None:
        data["greeting"] = update.greeting
    if update.voice is not None:
        data["voice"] = update.voice
        invalidate_voice_cache(cid)
    if update.speed is not None:
        data["speed"] = update.speed
        invalidate_voice_cache(cid)
    if update.receptionist_name is not None:
        data["receptionist_name"] = update.receptionist_name
    if update.business_type is not None:
        if not (USE_DB and tid and tid.get("business_vertical")):
            data["business_type"] = update.business_type
    if update.staff is not None:
        tenant_limits = db_tenant_get_by_client_id(cid)
        if tenant_limits and get_plan_limits:
            limits = get_plan_limits(tenant_limits)
            staff_max = limits.get("staff_max", 1)
            if len(update.staff) > staff_max:
                raise HTTPException(status_code=403, detail=f"Plan allows up to {staff_max} staff member(s). Upgrade to add more.")
        data["staff"] = finalize_staff_records_for_storage(update.staff)
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")
    audit_log("user", "business_info_updated", resource_type="config", client_id=cid, details={"fields": [k for k in update.model_dump(exclude_none=True)]}, request=request)
    resp_tenant: dict = {**tid, "client_id": cid}
    if "plan" not in resp_tenant or not resp_tenant.get("plan"):
        resp_tenant["plan"] = data.get("plan") or "free"
    resp_tenant.setdefault("twilio_phone_number", tid.get("twilio_phone_number") or "")
    return business_info_for_dashboard(resp_tenant)

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


def _analytics_iso_week_bounds_utc(now: Optional[datetime] = None) -> tuple:
    """Current ISO week: Monday 00:00 UTC (inclusive) through next Monday 00:00 UTC (exclusive)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    monday = now - timedelta(days=now.weekday())
    week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end_excl = week_start + timedelta(days=7)
    return week_start, week_end_excl


def _weekday_sun_zero(dt: datetime) -> int:
    """Dashboard uses Sun=0..Sat=6; Python weekday is Mon=0..Sun=6."""
    return (dt.weekday() + 1) % 7


@app.get("/api/analytics/summary")
async def get_analytics_summary(tenant: Optional[dict] = Depends(require_tenant), _: None = Depends(require_active_subscription)):
    """Pro: Peak call times, outcomes, total calls. Filtered by plan (call_log_days).
    by_day_of_week counts only the current ISO week (UTC); full history stays in DB/export."""
    days = _call_log_days(tenant)
    log = _load_call_log(days=days)
    week_start, week_end_excl = _analytics_iso_week_bounds_utc()
    week_period = {
        "by_day_of_week_period_start": week_start.date().isoformat(),
        "by_day_of_week_period_end": (week_end_excl - timedelta(days=1)).date().isoformat(),
        "by_day_of_week_timezone": "UTC",
    }
    if not log:
        return {
            "total_calls": 0,
            "by_outcome": {},
            "by_hour": {str(h): 0 for h in range(24)},
            "by_day_of_week": {str(d): 0 for d in range(7)},
            "client_id": get_db_client_id() or None,
            **week_period,
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
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                by_hour[str(dt.hour)] = by_hour.get(str(dt.hour), 0) + 1
                if week_start <= dt < week_end_excl:
                    wd = _weekday_sun_zero(dt)
                    by_day[str(wd)] = by_day.get(str(wd), 0) + 1
            except Exception:
                pass
    return {
        "total_calls": len(log),
        "by_outcome": by_outcome,
        "by_hour": by_hour,
        "by_day_of_week": by_day,
        "client_id": get_db_client_id() or None,
        **week_period,
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
    writer.writerow([
        "call_sid", "from_number", "to_number", "start_iso", "end_iso", "outcome", "duration_sec", "category", "created_at",
        "recording_sid", "recording_duration_sec", "recording_status", "call_summary",
    ])
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
            e.get("recording_sid", ""),
            e.get("recording_duration_sec", ""),
            e.get("recording_status", ""),
            e.get("call_summary", ""),
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=call_log.csv"},
    )


def _fetch_twilio_recording_bytes(recording_url: str) -> tuple:
    import httpx
    r = httpx.get(
        recording_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=120.0,
    )
    return r.status_code, r.content


@app.get("/api/analytics/calls/{call_sid}/recording")
async def get_call_recording_audio(
    call_sid: str,
    tenant: Optional[dict] = Depends(require_tenant),
    _: None = Depends(require_active_subscription),
):
    """Stream call recording (MP3) from Twilio using server-side credentials; tenant must own the call."""
    if not tenant or not USE_DB:
        raise HTTPException(status_code=404, detail="Recording not available")
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise HTTPException(status_code=503, detail="Recording playback is not configured")
    row = db_call_log_get_by_call_sid(tenant["client_id"], call_sid)
    if not row or not row.get("recording_url"):
        raise HTTPException(status_code=404, detail="Recording not available")
    code, data = await asyncio.to_thread(_fetch_twilio_recording_bytes, row["recording_url"])
    if code != 200:
        raise HTTPException(status_code=502, detail="Could not fetch recording")
    return Response(
        content=data,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="{call_sid}.mp3"',
            "Cache-Control": "private, max-age=300",
        },
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



def _get_client_id_from_call(request: Request) -> str:
    """Resolve client_id from call_sid query param (active_calls). Fallback to env CLIENT_ID or default."""
    call_sid = request.query_params.get("call_sid")
    if call_sid and call_sid in active_calls:
        return active_calls[call_sid].get("client_id") or CLIENT_ID or "default"
    return CLIENT_ID or "default"


def _summarize_call_recording_sync(call_sid: str, client_id: str, recording_url: str, duration_sec: Optional[int]) -> None:
    """Download Twilio recording, Whisper transcribe, short GPT summary; persist call_summary."""
    if not recording_url or not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return
    try:
        cap = int(os.getenv("CALL_SUMMARY_MAX_DURATION_SEC", "1800"))
    except ValueError:
        cap = 1800
    if duration_sec is not None and duration_sec > cap:
        logger.info("[Recording] Skip summary (duration %s sec > cap %s)", duration_sec, cap)
        return
    if (os.getenv("TWILIO_INTELLIGENCE_SERVICE_SID") or "").strip():
        logger.info("[Recording] TWILIO_INTELLIGENCE_SERVICE_SID is set; Phase 1 still uses OpenAI Whisper+GPT")
    try:
        import httpx
        with httpx.Client(timeout=120.0) as http:
            r = http.get(recording_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        if r.status_code != 200:
            logger.error("[Recording] Download failed status=%s call_sid=%s", r.status_code, call_sid)
            return
        audio_data = r.content
        _ensure_openai_client()
        bio = io.BytesIO(audio_data)
        bio.name = "recording.mp3"
        transcript = client.audio.transcriptions.create(model="whisper-1", file=bio)
        text = (getattr(transcript, "text", None) or "").strip()
        if not text:
            return
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Summarize this phone call in 2–4 clear sentences for a business owner dashboard. Mention caller intent (e.g. appointment, question, complaint) if clear. Be factual; do not invent details.",
                },
                {"role": "user", "content": text[:12000]},
            ],
            max_tokens=350,
            temperature=0.3,
        )
        summary = (resp.choices[0].message.content or "").strip()
        if not summary:
            return
        set_request_client_id(client_id)
        if USE_DB:
            db_call_log_update_summary(call_sid, client_id, summary)
        call_log_merge_recording(call_sid, call_summary=summary)
        if not USE_DB:
            _file_call_log_merge_recording(call_sid, call_summary=summary)
    except Exception:
        logger.exception("[Recording] Summarize failed call_sid=%s", call_sid)


async def _schedule_recording_summary(call_sid: str, client_id: str, recording_url: str, duration_sec: Optional[int]) -> None:
    try:
        await asyncio.to_thread(_summarize_call_recording_sync, call_sid, client_id, recording_url, duration_sec)
    except Exception:
        logger.exception("[Recording] Summary task failed call_sid=%s", call_sid)


@app.get("/api/phone/greeting-audio")
async def get_greeting_audio(request: Request):
    """Serve greeting audio using the voice selected in Settings. Per-client cache."""
    global greeting_audio_cache
    client_id = _get_client_id_from_call(request)
    set_request_client_id(client_id)
    cache_key = (client_id, _call_recording_enabled())
    cached = greeting_audio_cache.get(cache_key)
    if cached:
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=greeting.mp3",
                "Cache-Control": "public, max-age=3600",
                "Content-Length": str(len(cached))
            }
        )
    try:
        voice = get_tts_voice()
        greeting_text = add_sentence_pauses(get_greeting_text())
        greeting_audio = client.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=greeting_text,
            speed=get_tts_speed()
        )
        data = greeting_audio.content
        greeting_audio_cache[cache_key] = data
        print(f"🎵 Greeting audio generated for {client_id} (voice={voice})")
        return Response(
            content=data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=greeting.mp3",
                "Cache-Control": "public, max-age=3600",
                "Content-Length": str(len(data))
            }
        )
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
            data = fallback_audio.content
            greeting_audio_cache[cache_key] = data
            return Response(content=data, media_type="audio/mpeg", headers={"Content-Length": str(len(data))})
        except Exception as e2:
            print(f"❌ Fallback greeting audio failed: {e2}")
            raise HTTPException(status_code=500, detail=f"Failed to generate greeting: {e}")

@app.get("/api/phone/got-it-audio")
async def get_got_it_audio(request: Request):
    """Serve 'Got it, one moment' audio using the voice selected in Settings. Per-client cache."""
    global got_it_audio_cache
    client_id = _get_client_id_from_call(request)
    set_request_client_id(client_id)
    cached = got_it_audio_cache.get(client_id)
    if cached:
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=got-it.mp3",
                "Cache-Control": "public, max-age=3600",
                "Content-Length": str(len(cached))
            }
        )
    try:
        voice = get_tts_voice()
        got_it_text = "Got it, one moment."
        got_it_audio = client.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=add_sentence_pauses(got_it_text),
            speed=get_tts_speed()
        )
        data = got_it_audio.content
        got_it_audio_cache[client_id] = data
        print(f"🎵 'Got it' audio generated for {client_id} (voice={voice})")
        return Response(
            content=data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=got-it.mp3",
                "Cache-Control": "public, max-age=3600",
                "Content-Length": str(len(data))
            }
        )
    except Exception as e:
        print(f"❌ Failed to generate 'got it' audio: {e}")
        import traceback
        traceback.print_exc()
        try:
            fallback_audio = client.audio.speech.create(
                model="tts-1-hd",
                voice="fable",
                input=add_sentence_pauses(TTS_FALLBACK_TEXT),
                speed=1.0,
            )
            data = fallback_audio.content
            got_it_audio_cache[client_id] = data
            return Response(content=data, media_type="audio/mpeg", headers={"Content-Length": str(len(data))})
        except Exception as e2:
            print(f"❌ Fallback 'got it' audio failed: {e2}")
            raise HTTPException(status_code=500, detail=f"Failed to generate 'got it' audio: {e}")


@app.post("/api/sms/incoming")
async def handle_incoming_sms(request: Request):
    """Twilio webhook for incoming SMS. AI-powered mobile receptionist replies like a real person."""
    rid = getattr(request.state, "request_id", None)
    if not TWILIO_AVAILABLE:
        sms_debug("inbound_skipped", reason="twilio_not_available")
        sms_trace("inbound_early_exit", reason="twilio_not_available", request_id=rid)
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
    if not USE_DB:
        sms_debug("inbound_skipped", reason="database_not_enabled")
        sms_trace("inbound_early_exit", reason="database_not_enabled", request_id=rid)
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
    try:
        form_data = await request.form()
        form_dict = dict(form_data)
        sig_mode = "skipped"
        if (os.getenv("TWILIO_AUTH_TOKEN") or "").strip():
            sig_mode = "enforced"
        sms_trace(
            "inbound_form_parsed",
            request_id=rid,
            signature_mode=sig_mode,
            from_number=str(form_dict.get("From") or ""),
            to_number=str(form_dict.get("To") or ""),
            body_len=len(str(form_dict.get("Body") or "")),
            message_sid=str(form_dict.get("MessageSid") or form_dict.get("SmsMessageSid") or ""),
            num_media=str(form_dict.get("NumMedia") or ""),
        )
        if not _validate_twilio_webhook(request, form_dict):
            auth_warning(
                "sms_webhook_invalid_signature",
                path=request.url.path,
                request_id=rid,
            )
            sms_trace("inbound_signature_invalid", request_id=rid, signature_mode=sig_mode)
            return Response(content="", status_code=403, media_type="application/xml")
        sms_trace("inbound_signature_ok", request_id=rid, signature_mode=sig_mode)
        from_number = form_data.get("From", "").strip()
        to_number = form_data.get("To", "").strip()
        body = (form_data.get("Body", "") or "").strip()
        msg_sid = (form_data.get("MessageSid") or form_data.get("SmsMessageSid") or "").strip()
        if not from_number or not to_number or not body:
            sms_info("inbound_skipped", reason="missing_fields", message_sid=msg_sid or None)
            sms_trace(
                "inbound_early_exit",
                reason="missing_fields",
                request_id=rid,
                has_from=bool(from_number),
                has_to=bool(to_number),
                has_body=bool(body),
                message_sid=msg_sid or None,
            )
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
        tenant = db_tenant_get_by_phone(to_number)
        if not tenant:
            sms_info("inbound_skipped", reason="unknown_to_number", to_number=to_number, message_sid=msg_sid or None)
            sms_trace(
                "inbound_tenant_not_found",
                request_id=rid,
                to_number=to_number,
                message_sid=msg_sid or None,
                hint="ensure_twilio_to_matches_tenant_twilio_phone_number",
            )
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
        set_request_client_id(tenant["client_id"])
        sms_info(
            "inbound_received",
            client_id=tenant["client_id"],
            from_number=from_number,
            to_number=to_number,
            body_len=len(body),
            message_sid=msg_sid or None,
            request_id=rid,
        )
        sms_trace(
            "inbound_tenant_resolved",
            request_id=rid,
            client_id=tenant["client_id"],
            tenant_name=(tenant.get("name") or "")[:80],
            message_sid=msg_sid or None,
        )
        kw = _sms_compliance_keyword(body)
        if kw:
            sms_trace(
                "inbound_compliance_keyword",
                request_id=rid,
                keyword=kw,
                client_id=tenant["client_id"],
                message_sid=msg_sid or None,
            )
            cid = tenant["client_id"]
            if kw == "stop":
                db_sms_opt_out_set(from_number, cid)
                send_sms(
                    from_number,
                    "You've opted out and won't get more texts from this number. Reply START to get messages again. Msg and data rates may apply.",
                    from_override=to_number,
                    force=True,
                )
            elif kw == "start":
                db_sms_opt_out_clear(from_number, cid)
                send_sms(
                    from_number,
                    "You're subscribed again to texts from this number. Msg and data rates may apply. Reply STOP to opt out.",
                    from_override=to_number,
                    force=True,
                )
            elif kw == "help":
                send_sms(
                    from_number,
                    "Call Surge: texts for appointments and replies from this business. Msg and data rates may apply. Reply STOP to opt out. Help: info@nuvatrahq.com",
                    from_override=to_number,
                    force=True,
                )
            sms_trace("inbound_compliance_handled", request_id=rid, keyword=kw, client_id=cid)
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
        if USE_DB and db_sms_opt_out_is_blocked(from_number, tenant["client_id"]):
            sms_info(
                "inbound_blocked_opt_out",
                client_id=tenant["client_id"],
                from_number=from_number,
            )
            sms_trace(
                "inbound_early_exit",
                reason="recipient_opted_out",
                request_id=rid,
                client_id=tenant["client_id"],
            )
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
        staff_handled = _maybe_handle_staff_sms_approval(from_number, body, tenant, to_number)
        if staff_handled:
            sms_trace("inbound_staff_command_handled", request_id=rid, client_id=tenant["client_id"])
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
        # Pre-SMS usage check: allow overage, log for billing (Option B)
        if get_plan_limits:
            limits = get_plan_limits(tenant)
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            usage = db_usage_get(tenant["client_id"], month)
            total = (usage.get("voice_minutes") or 0) + (usage.get("sms_count") or 0)
            cap = limits.get("minutes_cap", 999999)
            sms_trace(
                "inbound_usage_snapshot",
                request_id=rid,
                client_id=tenant["client_id"],
                month=month,
                voice_minutes=usage.get("voice_minutes") or 0,
                sms_count=usage.get("sms_count") or 0,
                combined_total=total,
                minutes_cap=cap,
                at_or_over_cap=total >= cap,
            )
            if total >= cap:
                audit_log("usage", "overage_exceeded", client_id=tenant["client_id"], details={"month": month, "total": total, "cap": cap}, request=request)
        apt = db_appointments_get_by_phone_for_sms(from_number) if USE_DB else None
        if apt:
            sms_debug(
                "inbound_context",
                apt_id=apt.get("id"),
                apt_status=apt.get("status"),
                body_len=len(body),
                from_number=from_number,
            )
            sms_trace(
                "inbound_appointment_context",
                request_id=rid,
                apt_id=apt.get("id"),
                apt_status=apt.get("status"),
                body_len=len(body),
            )
        else:
            sms_debug("inbound_no_pending_appointment", body_len=len(body), from_number=from_number)
            sms_trace("inbound_no_appointment_for_number", request_id=rid, body_len=len(body))
        # Persist email from SMS while appointment is still pending_customer (e.g. "my email is x@y.com")
        if apt and apt.get("status") == "pending_customer" and USE_DB and apt.get("id"):
            em_match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", body or "", re.I)
            if em_match:
                em = em_match.group(0).strip()
                try:
                    aid = int(apt["id"])
                    db_appointments_update(aid, email=em)
                    apt = db_appointments_get_by_id(aid) or apt
                    sms_info(
                        "inbound_customer_email_saved_from_reply",
                        apt_id=aid,
                        client_id=tenant["client_id"],
                    )
                except Exception as e:
                    logger.warning(
                        "inbound save email from SMS failed apt_id=%s: %s",
                        apt.get("id"),
                        e,
                        exc_info=True,
                    )
        session = db_sms_session_get(from_number, tenant["client_id"]) if USE_DB else None
        messages = (session["messages"] if session else []) if session else []
        prior_turns = len(messages)
        messages.append({"role": "user", "content": body})
        sms_trace(
            "inbound_session_loaded",
            request_id=rid,
            prior_turns=prior_turns,
            session_existed=session is not None,
        )
        # If they have an appointment awaiting their confirmation (pending_customer) and they reply yes/looks good, promote to pending_review so store can Accept/Decline
        if apt and apt.get("status") == "pending_customer" and _is_sms_confirmation(body):
            sms_trace(
                "inbound_customer_confirm_branch",
                request_id=rid,
                apt_id=apt.get("id"),
                client_id=tenant["client_id"],
            )
            apt_after = apt
            if USE_DB and apt.get("id"):
                aid = int(apt["id"])
                apt_full = db_appointments_get_by_id(aid) or apt
                date = (apt_full.get("date") or "").strip()
                time_raw = (apt_full.get("time") or "").strip()
                time_hhmm = _normalize_time_to_hhmm(time_raw) or time_raw
                staff_for = (apt_full.get("staff_id") or "").strip() or None
                if not is_slot_available(date, time_hhmm, DEFAULT_SLOT_DURATION_MINUTES, staff_for):
                    sorry = (
                        "Sorry — that time was just taken and we can't hold it anymore. "
                        "Text us another time that works or call the shop. Msg & data rates may apply. Reply STOP to opt out."
                    )
                    send_ok = send_sms(from_number, sorry, from_override=to_number)
                    sms_trace(
                        "inbound_customer_confirm_slot_unavailable",
                        request_id=rid,
                        apt_id=aid,
                        send_sms_ok=send_ok,
                    )
                    messages.append({"role": "assistant", "content": sorry})
                    try:
                        db_sms_session_upsert(from_number, tenant["client_id"], messages, apt["id"])
                    except Exception as upsert_err:
                        sms_info(
                            "inbound_session_persist_failed",
                            request_id=rid,
                            client_id=tenant["client_id"],
                            error_type=type(upsert_err).__name__,
                            phase="pending_customer_confirm_slot_taken",
                        )
                        logger.warning("db_sms_session_upsert failed (slot taken path): %s", upsert_err, exc_info=True)
                    return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
                reserve_slot(date, time_hhmm, aid, DEFAULT_SLOT_DURATION_MINUTES, staff_for)
                db_appointments_update(aid, status="pending_review")
                apt_after = db_appointments_get_by_id(aid) or apt_full
            try:
                update_caller_memory(
                    from_number,
                    last_reason="details confirmed; awaiting store approval",
                    increment_count=False,
                    data_patch={"last_pending_review_apt_id": apt.get("id")},
                )
            except Exception:
                pass
            _notify_staff_pending_review(apt_after, tenant, to_number)
            sms_info(
                "customer_confirmed_pending_to_review",
                apt_id=apt.get("id"),
                client_id=tenant["client_id"],
                from_number=from_number,
            )
            reply = (
                "Thanks! We've sent this to the store. We'll text you when they confirm. "
                "Msg & data rates may apply. Reply STOP to opt out."
            )
            send_ok = send_sms(from_number, reply, from_override=to_number)
            sms_trace(
                "inbound_customer_confirm_reply_sent",
                request_id=rid,
                send_sms_ok=send_ok,
                reply_len=len(reply),
            )
            messages.append({"role": "assistant", "content": reply})
            try:
                db_sms_session_upsert(from_number, tenant["client_id"], messages, apt["id"])
            except Exception as upsert_err:
                sms_info(
                    "inbound_session_persist_failed",
                    request_id=rid,
                    client_id=tenant["client_id"],
                    error_type=type(upsert_err).__name__,
                    phase="pending_customer_confirm",
                )
                logger.warning("db_sms_session_upsert failed (pending_customer path): %s", upsert_err, exc_info=True)
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
        apt_info = ""
        if apt:
            apt_info = f"The customer has a PENDING appointment: Name {apt.get('name','')}, {apt.get('date','')} at {_hhmm_to_ampm(apt.get('time','') or '')}, service: {apt.get('reason','')}."
        else:
            apt_info = "The customer does not have a pending appointment in the system."
        pending_customer_note = ""
        if apt and apt.get("status") == "pending_customer":
            pending_customer_note = (
                "\nThey are refining DETAILS before the booking goes to the shop for approval. "
                "Echo date, time, name, and service back clearly when they change something. "
                "Do not say the shop already confirmed it—only that you will pass it along once they finalize. "
                "Ask them to reply YES or CONFIRM only when everything looks exactly right; that submits the request "
                "to the business for approval (you cannot approve it yourself)."
            )
        business_name = get_business_info().get("name", "us")
        history_str = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-10:]])
        sys_prompt = f"""You're the friendly text receptionist for {business_name}. Keep replies short (1-3 sentences), casual, like texting a friend.

{apt_info}{pending_customer_note}

They just texted: "{body}"

Previous conversation:
{history_str}

Respond naturally. If they confirm it's correct, say we'll text when the business confirms. If they want changes (date, time, name, etc.), acknowledge and say we'll update it—don't make up new details. For other questions (hours, location, services), answer from your knowledge. Be warm and helpful."""

        openai_configured = bool((os.getenv("OPENAI_API_KEY") or "").strip())
        sms_trace(
            "inbound_ai_prepare",
            request_id=rid,
            client_id=tenant["client_id"],
            model="gpt-4o-mini",
            openai_key_configured=openai_configured,
            history_turns=len(messages),
            apt_id=apt.get("id") if apt else None,
            apt_status=(apt.get("status") if apt else None) or "",
            pending_customer_flow=bool(pending_customer_note),
            sys_prompt_len=len(sys_prompt),
            user_body_len=len(body),
        )
        reply = ""
        if not openai_configured:
            sms_info(
                "inbound_ai_skipped_no_openai_key",
                request_id=rid,
                client_id=tenant["client_id"],
            )
        else:
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            try:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": body}],
                    temperature=0.8,
                    max_tokens=150,
                )
                reply = (resp.choices[0].message.content or "").strip()
                finish_reason = getattr(resp.choices[0], "finish_reason", None)
                sms_trace(
                    "inbound_ai_complete",
                    request_id=rid,
                    reply_len=len(reply),
                    finish_reason=finish_reason or "",
                    empty_reply=not bool(reply),
                )
            except Exception as ai_err:
                sms_info(
                    "inbound_ai_openai_failed",
                    request_id=rid,
                    client_id=tenant["client_id"],
                    error_type=type(ai_err).__name__,
                    error=str(ai_err)[:400],
                )
                logger.warning("SMS OpenAI completion failed: %s", ai_err, exc_info=True)
                reply = ""
        if not reply:
            sms_info(
                "inbound_ai_empty_reply",
                request_id=rid,
                client_id=tenant["client_id"],
                openai_configured=openai_configured,
            )
            if apt and str(apt.get("status") or "") == "pending_customer":
                reply = (
                    "Thanks — we got that. Reply YES when everything looks right and we'll send it to the shop. "
                    "Msg & data rates may apply. Reply STOP to opt out."
                )
            else:
                reply = (
                    "Thanks — we got your message and will follow up shortly. "
                    "Msg & data rates may apply. Reply STOP to opt out."
                )
            sms_trace(
                "inbound_ai_fallback_reply_used",
                request_id=rid,
                pending_customer=bool(apt and str(apt.get("status") or "") == "pending_customer"),
            )
        send_ok = False
        if reply:
            send_ok = bool(send_sms(from_number, reply, from_override=to_number))
            sms_trace(
                "inbound_ai_reply_send_result",
                request_id=rid,
                send_sms_ok=send_ok,
                reply_len=len(reply),
            )
        messages.append({"role": "assistant", "content": reply})
        try:
            db_sms_session_upsert(from_number, tenant["client_id"], messages, apt["id"] if apt else None)
            sms_trace(
                "inbound_session_persist_ok",
                request_id=rid,
                messages_stored=len(messages),
                appointment_id_attached=apt.get("id") if apt else None,
            )
        except Exception as upsert_err:
            sms_info(
                "inbound_session_persist_failed",
                request_id=rid,
                client_id=tenant["client_id"],
                error_type=type(upsert_err).__name__,
                phase="ai_reply_path",
            )
            logger.warning("db_sms_session_upsert failed (AI path): %s", upsert_err, exc_info=True)
        # Lead capture: when no pending appointment and plan allows, treat as inquiry
        if not apt and get_plan_limits and get_plan_limits(tenant).get("has_lead_capture"):
            body_lower = (body or "").lower().strip()
            if len(body_lower) > 5 and body_lower not in ("yes", "no", "ok", "nope", "sure", "thanks"):
                lead_inserted = False
                try:
                    db_leads_insert(tenant["client_id"], None, from_number, body[:500] if body else "inquiry", "sms")
                    lead_inserted = True
                except Exception as lead_err:
                    sms_info(
                        "inbound_lead_insert_failed",
                        request_id=rid,
                        client_id=tenant["client_id"],
                        error_type=type(lead_err).__name__,
                    )
                    logger.warning("db_leads_insert SMS failed: %s", lead_err, exc_info=True)
                sms_trace(
                    "inbound_lead_capture",
                    request_id=rid,
                    lead_inserted=lead_inserted,
                    body_qualifies=True,
                )
                # SMS automation: after_inquiry - send template to customer
                if USE_DB:
                    automations = db_sms_automations_get_by_trigger(tenant["client_id"], "after_inquiry")
                    sms_trace(
                        "inbound_after_inquiry_automations",
                        request_id=rid,
                        automation_count=len(automations),
                    )
                    for auto in automations:
                        template = (auto.get("template") or "").strip()
                        if not template:
                            sms_trace(
                                "inbound_automation_skipped",
                                request_id=rid,
                                automation_id=str(auto.get("id") or ""),
                                reason="empty_template",
                            )
                            continue
                        cfg = load_client_config(tenant["client_id"])
                        business_name = (cfg.get("business_name") or cfg.get("name") or "us") if cfg else "us"
                        msg = template.replace("{business_name}", business_name).replace("{name}", business_name)
                        try:
                            set_request_client_id(tenant["client_id"])
                            send_sms(from_number, msg[:1600], from_override=to_number)
                            sms_trace(
                                "inbound_automation_sent",
                                request_id=rid,
                                automation_id=str(auto.get("id") or ""),
                                template_len=len(msg),
                            )
                        except Exception as auto_err:
                            sms_info(
                                "inbound_automation_send_failed",
                                request_id=rid,
                                automation_id=str(auto.get("id") or ""),
                                error_type=type(auto_err).__name__,
                            )
                            logger.warning("after_inquiry automation send failed: %s", auto_err, exc_info=True)
        sms_trace("inbound_pipeline_done", request_id=rid, client_id=tenant["client_id"])
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
    except Exception as e:
        sms_info(
            "inbound_webhook_unhandled_exception",
            error_type=type(e).__name__,
            error=str(e)[:400],
            request_id=rid,
        )
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
        voice_info(
            "incoming_call_webhook",
            remote_ip=request.client.host if request.client else "unknown",
            request_id=getattr(request.state, "request_id", None),
        )
        form_data = await request.form()
        form_dict = dict(form_data)
        if not _validate_twilio_webhook(request, form_dict):
            auth_warning(
                "voice_webhook_invalid_signature",
                path=request.url.path,
                request_id=getattr(request.state, "request_id", None),
            )
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
        call_sid = form_data.get("CallSid")
        from_number = form_data.get("From")
        to_number = form_data.get("To")
        
        voice_info(
            "incoming_call",
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
        )

        # Multi-tenant: resolve tenant by To number and set request context
        tenant = db_tenant_get_by_phone(to_number or "") if USE_DB else None
        if tenant:
            set_request_client_id(tenant["client_id"])
            voice_info(
                "tenant_resolved_by_to_number",
                client_id=tenant["client_id"],
                tenant_name=tenant.get("name") or "",
                to_number=to_number,
            )
        elif CLIENT_ID:
            set_request_client_id(CLIENT_ID)
            voice_info(
                "tenant_fallback_client_id_env",
                client_id_env=CLIENT_ID,
                to_number=to_number,
            )
        else:
            voice_info("tenant_fallback_default", to_number=to_number)
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
        voice_info(
            "call_session_started",
            call_sid=call_sid,
            client_id=client_id,
            from_number=from_number,
            to_number=to_number,
        )
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
        
        base_url = _twilio_base_url(request)
        if not base_url:
            logger.error(
                "[VOICE] incoming_call missing public base URL; set PUBLIC_BASE_URL (or NGROK_URL), "
                "or ensure the reverse proxy forwards Host and X-Forwarded-Proto."
            )
            voice_info("incoming_call_missing_public_base_url", call_sid=call_sid)
            fail_twiml = VoiceResponse()
            fail_twiml.say(
                "Sorry, this phone line is not fully configured yet. Please try again later.",
                voice="alice",
            )
            fail_twiml.hangup()
            return Response(content=str(fail_twiml), media_type="application/xml")

        active_calls[call_sid]["twilio_public_base_url"] = base_url

        # Create TwiML response
        response = VoiceResponse()

        if TWILIO_AVAILABLE and VoiceResponse and _call_recording_enabled():
            cb = f"{base_url.rstrip('/')}/api/phone/recording-complete"
            start = response.start()
            start.recording(
                channels="dual",
                recording_status_callback=cb,
                recording_status_callback_method="POST",
            )

        # Greeting audio uses voice from Settings; pass call_sid so we resolve client_id
        greeting_audio_url = f"{base_url}/api/phone/greeting-audio?call_sid={call_sid}"

        from voice.stt_config import deepgram_env_block_reason, voice_stt_provider

        use_deepgram_stt = _voice_stt_use_deepgram()
        voice_info(
            "incoming_call_stt_provider",
            provider="deepgram" if use_deepgram_stt else "twilio",
            call_sid=call_sid,
        )
        if voice_stt_provider() == "deepgram" and not use_deepgram_stt:
            env_r = deepgram_env_block_reason()
            if env_r:
                voice_info("deepgram_requested_but_disabled", reason=env_r, call_sid=call_sid)
            else:
                voice_info(
                    "deepgram_requested_but_disabled",
                    reason="twilio_client_unavailable_or_twilio_not_installed",
                    call_sid=call_sid,
                )

        if use_deepgram_stt:
            from twilio.twiml.voice_response import Connect, Stream

            from voice.media_token import mint_media_stream_token
            from voice.stt_config import http_to_ws_base

            response.play(greeting_audio_url)
            wss_base = http_to_ws_base(base_url)
            stream_url = f"{wss_base}/api/phone/media"
            token = mint_media_stream_token(call_sid)
            connect = Connect()
            stream = Stream(url=stream_url)
            if token:
                stream.parameter(name="token", value=token)
            connect.append(stream)
            response.append(connect)
            got_it_audio_url = f"{base_url}/api/phone/got-it-audio?call_sid={call_sid}"
            response.play(got_it_audio_url)
            response.redirect(f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST")
            return Response(content=str(response), media_type="application/xml")

        gather = response.gather(
            input='speech',
            action=f"{base_url}/api/phone/process-speech",
            method='POST',
            speech_timeout='auto',
            language='en-US',  # Start with English, will be updated dynamically after first detection
            hints='appointment, schedule, message, hours, contact, help'
        )
        gather.play(greeting_audio_url)

        # If no input, redirect to process speech anyway
        response.redirect(f"{base_url}/api/phone/process-speech", method='POST')

        return Response(content=str(response), media_type="application/xml")
    
    except Exception as e:
        print(f"❌ Error handling incoming call: {e}")
        import traceback
        traceback.print_exc()
        response = VoiceResponse()
        base_url = _twilio_base_url(request)

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


@app.post("/api/phone/recording-complete")
async def handle_recording_complete(request: Request):
    """Twilio recording status callback for full-call dual-channel recording."""
    if not TWILIO_AVAILABLE:
        return Response(content="", status_code=200, media_type="text/plain")
    try:
        form_data = await request.form()
        form_dict = dict(form_data)
        if not _validate_twilio_webhook(request, form_dict):
            return Response(content="Forbidden", status_code=403, media_type="text/plain")
        call_sid = (form_data.get("CallSid") or "").strip()
        recording_sid = (form_data.get("RecordingSid") or "").strip() or None
        recording_url = (form_data.get("RecordingUrl") or "").strip() or None
        recording_status = (form_data.get("RecordingStatus") or "").strip() or None
        dur_raw = (form_data.get("RecordingDuration") or "").strip()
        duration_sec: Optional[int] = None
        if dur_raw:
            try:
                duration_sec = int(float(dur_raw))
            except (TypeError, ValueError):
                pass

        client_id: Optional[str] = None
        if call_sid and call_sid in active_calls:
            client_id = active_calls[call_sid].get("client_id")
        if not client_id and USE_DB:
            client_id = db_call_log_get_client_id_by_call_sid(call_sid)
        if not client_id:
            client_id = CLIENT_ID or "default"
        set_request_client_id(client_id)

        if USE_DB:
            db_call_log_update_recording(
                call_sid,
                client_id,
                recording_sid=recording_sid,
                recording_url=recording_url,
                recording_duration_sec=duration_sec,
                recording_status=recording_status,
            )
        call_log_merge_recording(
            call_sid,
            recording_sid=recording_sid,
            recording_url=recording_url,
            recording_duration_sec=duration_sec,
            recording_status=recording_status,
        )
        if not USE_DB:
            _file_call_log_merge_recording(
                call_sid,
                recording_sid=recording_sid,
                recording_url=recording_url,
                recording_duration_sec=duration_sec,
                recording_status=recording_status,
            )

        st = (recording_status or "").lower()
        if st == "completed" and recording_url and _call_summary_enabled():
            asyncio.create_task(_schedule_recording_summary(call_sid, client_id, recording_url, duration_sec))
        return Response(content="", status_code=200, media_type="text/plain")
    except Exception as e:
        logger.exception("recording-complete webhook error: %s", e)
        return Response(content="", status_code=200, media_type="text/plain")


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

        print(f"🎤 Speech received: {speech_result} (confidence: {confidence})")

        _restore_call_context(call_sid or "")
        base_url = _twilio_base_url(request)

        from voice.utterance import apply_caller_utterance

        outcome = await apply_caller_utterance(
            call_sid or "",
            speech_result or "",
            float(confidence or 0),
            base_url,
        )
        if outcome.mode == "replace_call_twiml" and outcome.replacement_twiml:
            return Response(content=outcome.replacement_twiml, media_type="application/xml")

        response = VoiceResponse()
        got_it_audio_url = f"{base_url}/api/phone/got-it-audio?call_sid={call_sid}"
        response.play(got_it_audio_url)
        response.redirect(f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST")

        return Response(content=str(response), media_type="application/xml")
    
    except Exception as e:
        print(f"❌ Error processing speech: {e}")
        import traceback
        traceback.print_exc()
        
        # On error, offer to forward to a real person
        response = VoiceResponse()
        base_url = _twilio_base_url(request)

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
            # Avoid redirect-only loops on errors: prompt once inside Gather, then end the call.
            error_text = "I'm sorry, I didn't catch that. Could you repeat?"
            error_encoded = quote(error_text)
            tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={get_tts_voice()}"
            response.play(tts_audio_url)
            gather = response.gather(
                input="speech",
                action=f"{base_url}/api/phone/process-speech",
                method="POST",
                speech_timeout="auto",
                timeout=10,
            )
            gather.say("Please speak after the tone.", voice="alice")
            response.say("We're having trouble on this line. Goodbye.", voice="alice")
            response.hangup()
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

@app.websocket("/api/phone/media")
async def phone_media_websocket(websocket: WebSocket):
    """Twilio Media Streams → Deepgram Nova-2 live STT (when VOICE_STT_PROVIDER=deepgram)."""
    if not TWILIO_AVAILABLE or not twilio_client:
        await websocket.close(code=1011)
        return
    from voice.media_ws import handle_phone_media_websocket

    await handle_phone_media_websocket(websocket, twilio_client)


@app.post("/api/phone/stream")
async def handle_media_stream(request: Request):
    """
    Legacy placeholder. Real-time media uses WebSocket ``GET /api/phone/media`` (Twilio Media Streams).
    """
    return {
        "message": "Use WebSocket wss://…/api/phone/media for Twilio Media Streams (VOICE_STT_PROVIDER=deepgram).",
        "websocket_path": "/api/phone/media",
    }

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
        # base_url needed for forward_call_to_business in all branches
        base_url = _twilio_base_url(request)
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
        response = VoiceResponse()
        
        if status == "ready":
            # Audio is ready - play it
            audio_url = status_data.get("audio_url")
            if audio_url:
                response.play(audio_url)
                try:
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
                    
                    # If no input, prompt once then goodbye (same TTS voice as receptionist)
                    still_there_url = f"{base_url}/api/phone/tts-audio?text={quote('Still there?')}&voice={get_tts_voice()}"
                    response.play(still_there_url)
                    gather2 = response.gather(
                        input='speech',
                        action=f"{base_url}/api/phone/process-speech",
                        method='POST',
                        speech_timeout='auto',
                        language=twilio_lang_code
                    )
                    forwarding_phone = (get_business_info().get("forwarding_phone") or "").strip()
                    if forwarding_phone:
                        if call_sid and call_sid in active_calls:
                            active_calls[call_sid]["outcome"] = "forwarded"
                        if call_sid:
                            call_log_set_outcome(call_sid, "forwarded")
                        print(
                            f"🔄 No speech after still there — forwarding to business phone: {forwarding_phone}"
                        )
                        append_forward_call_verbs(
                            response, forwarding_phone, base_url, detected_lang
                        )
                    else:
                        goodbye_text = "Thanks for calling! Have a wonderful day!"
                        goodbye_url = f"{base_url}/api/phone/tts-audio?text={quote(goodbye_text)}&voice={get_tts_voice()}"
                        response.play(goodbye_url)
                        response.hangup()
                except Exception as e:
                    logger.warning("respond ready/goodbye block failed: %s: %s", type(e).__name__, e)
                    response = VoiceResponse()
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
        logger.exception("Error in respond endpoint: %s", e)
        import traceback
        traceback.print_exc()
        response = VoiceResponse()
        base_url = _twilio_base_url(request)
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
            bu = _twilio_base_url(request)
            if bu:
                response.redirect(f"{bu}/api/phone/process-speech", method='POST')
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
            bu = _twilio_base_url(request)
            if bu:
                response.redirect(f"{bu}/api/phone/process-speech", method='POST')
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
        
        # Get AI response (always include booked slots; skip cache so prompt and availability check match)
        messages = [
            {"role": "system", "content": get_system_prompt(detected_lang, call_data.get("caller_memory"), include_booked_slots=True, skip_slots_cache=True)}
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

        base_url = _twilio_base_url(request)

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
        base_url = _twilio_base_url(request)

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
    print("Starting Call Surge Backend Server")
    print("="*50)
    print(f"Server will run on: http://0.0.0.0:8000")
    print(f"Local access: http://localhost:8000")
    print("="*50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

