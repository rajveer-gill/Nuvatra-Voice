import sys

from fastapi import FastAPI, HTTPException, Request, Form, Depends, WebSocket
from contextlib import asynccontextmanager
import asyncio
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response, JSONResponse
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from typing import Optional, List, Literal, Any
import uuid
import logging
import openai
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

logger = logging.getLogger("nuvatra")
import os
import runtime  # process-wide mutable state (USE_DB, etc.); read as runtime.X
from dotenv import load_dotenv
from datetime import date, datetime, timezone, timedelta
import hmac
import secrets
import math
import time
import json
import hashlib
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
    print(
        "WARNING: Twilio not installed - phone features will be disabled. Install with: pip install twilio"
    )

try:
    from plans import get_plan_limits
except ImportError:
    get_plan_limits = None  # type: ignore

from subscription_access import get_tenant_subscription_state

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

from prompts.receptionist import appointment_focus_guidance, build_system_prompt, caller_message_suggests_pricing, latest_user_message
from voice.call_session_store import MemoryCallSessionStore, get_call_session_store
from settings import get_settings
from security.webhooks import (
    validate_twilio_webhook as validate_twilio_signature,
    verify_stripe_event,
)
from security.redaction import mask_phone_e164

# Load .env from backend directory (where this script is located)
# Get the directory where this script is located
_this_file = Path(__file__).resolve()
_backend_dir = _this_file.parent

# The .env file is in the backend directory
env_path = _backend_dir / ".env"

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
    mask_phone,
    sms_debug,
    sms_info,
    sms_trace,
    system_debug,
    system_info,
    usage_warning,
    voice_call_phase,
    voice_debug,
    voice_forward,
    voice_info,
    voice_respond_branch,
    voice_trace,
    voice_warning,
    webhook_timing_middleware,
)

from booking_fields import (
    assistant_asked_service_recently,
    booking_context_from_business,
    is_valid_booking_date,
    looks_like_booking_time,
    normalize_and_validate_booking,
    normalize_booking_time,
    service_choice_resolved,
    service_prompt_message,
)


# _public_base_url now lives in deps (cross-cutting webhook/url helper); re-export.
from deps import _public_base_url  # noqa: E402,F401


def _derived_public_base_from_request(request: Request) -> str:
    """When PUBLIC_BASE_URL is unset, derive https://host from the inbound webhook (Render/proxies send X-Forwarded-*)."""
    host = (
        (request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
        .split(",")[0]
        .strip()
    )
    if not host:
        return ""
    proto = (
        (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    )
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
        "services_ty=%s specials_ty=%s reservation_rules_ty=%s staff_ty=%s "
        "config_source=%s greeting_len=%s voice=%s receptionist_set=%s",
        prefix,
        sorted(out.keys()),
        _tn("services"),
        _tn("specials"),
        _tn("reservation_rules"),
        _tn("staff"),
        client_config_source(str(cid)) if cid else "none",
        len((out.get("greeting") or "")),
        out.get("voice"),
        bool((out.get("receptionist_name") or "").strip()),
    )


def _sentry_traces_sample_rate() -> float:
    raw = (os.environ.get("SENTRY_TRACES_SAMPLE_RATE") or "").strip()
    if raw:
        try:
            return max(0.0, min(1.0, float(raw)))
        except ValueError:
            pass
    env = (os.environ.get("SENTRY_ENVIRONMENT") or "production").lower()
    return 1.0 if env in ("development", "dev", "local", "test") else 0.1


# Caller PII (phone numbers, names, message bodies) must never leave the app in
# plaintext. The log helpers in security/redaction.py only cover our own log
# lines — Sentry events (exceptions, breadcrumbs, request data) bypass them, so
# we scrub at the SDK boundary too.
_SENTRY_PII_KEYS = {
    "from",
    "to",
    "body",
    "phone",
    "phone_number",
    "caller",
    "caller_phone",
    "name",
    "customer_name",
    "email",
    "password",
    "token",
}
_SENTRY_PHONE_RE = re.compile(r"\+?\d[\d\-\s().]{6,}\d")
_SENTRY_DROP_HEADERS = (
    "authorization",
    "cookie",
    "x-twilio-signature",
    "stripe-signature",
)


def _sentry_scrub(value, _depth: int = 0):
    if _depth > 6:
        return value
    if isinstance(value, str):
        return _SENTRY_PHONE_RE.sub("[redacted-phone]", value)
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _SENTRY_PII_KEYS:
                out[k] = "[redacted]"
            else:
                out[k] = _sentry_scrub(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_sentry_scrub(v, _depth + 1) for v in value]
    return value


def _sentry_before_send(event, _hint):
    try:
        req = event.get("request")
        if isinstance(req, dict):
            req.pop("data", None)  # raw request bodies (SMS text, form fields)
            headers = req.get("headers")
            if isinstance(headers, dict):
                for key in list(headers.keys()):
                    if isinstance(key, str) and key.lower() in _SENTRY_DROP_HEADERS:
                        headers[key] = "[redacted]"
        return _sentry_scrub(event)
    except Exception:
        return event


sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
    traces_sample_rate=_sentry_traces_sample_rate(),
    integrations=[StarletteIntegration(), FastApiIntegration()],
    send_default_pii=False,
    before_send=_sentry_before_send,
)


# Verify API key is loaded
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print(f"ERROR: OPENAI_API_KEY not found!")
    print(f"Checked path: {env_path}")
    print(f"Path exists: {env_path.exists()}")
    print(
        f"Make sure your .env file is in the backend directory with OPENAI_API_KEY=your_key"
    )
    raise ValueError(
        f"OPENAI_API_KEY not found! Checked: {env_path}\n"
        f"Make sure your .env file is in the backend directory with OPENAI_API_KEY=your_key"
    )
else:
    print("OPENAI_API_KEY loaded successfully")


_openai_pre_warm_disabled = False


async def pre_warm_openai():
    """Pre-warm OpenAI client. Greeting/got-it clips pre-generate on startup, settings save, and incoming calls."""
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


def _server_error(
    context: str,
    exc: Exception,
    *,
    status_code: int = 500,
    public_detail: str = "Internal server error",
) -> HTTPException:
    """Log the real exception server-side; return a client-safe HTTPException.

    Raw exception strings from the DB driver, Stripe, OpenAI, or Twilio can embed
    connection strings, partial keys, or internal hostnames — never echo str(e)
    to clients. Callers do `raise _server_error("context", e)`.
    """
    logger.error("%s: %s", context, exc, exc_info=True)
    return HTTPException(status_code=status_code, detail=public_detail)


def _assert_secure_production_config() -> None:
    """Fail closed at boot.

    A DB-backed (i.e. multi-tenant production) deployment MUST have JWT-auth and
    webhook-signature secrets configured, and MUST NOT pin all data to a single
    legacy CLIENT_ID. This guarantees that a single missing/typo'd env var can
    never silently disable authentication or webhook validation — the process
    refuses to serve instead. DATABASE_URL is the production signal (it is what
    flips runtime.USE_DB on). ALLOW_INSECURE_WEBHOOKS is the explicit, deliberate dev
    opt-out and bypasses the guard.
    """
    if not (os.getenv("DATABASE_URL") or "").strip():
        return  # local / in-memory dev mode
    if (os.getenv("ALLOW_INSECURE_WEBHOOKS") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    problems: List[str] = []
    for var in ("CLERK_JWKS_URL", "CLERK_ISSUER", "CLERK_AUDIENCE"):
        if not (os.getenv(var) or "").strip():
            problems.append(f"{var} unset — JWT auth would be disabled")
    if not (os.getenv("TWILIO_AUTH_TOKEN") or "").strip():
        problems.append(
            "TWILIO_AUTH_TOKEN unset — Twilio webhook signatures would not be verified"
        )
    if (os.getenv("CLIENT_ID") or "").strip():
        problems.append(
            "CLIENT_ID is set — would pin all tenant data to one client in multi-tenant mode"
        )
    if problems:
        raise RuntimeError(
            "Refusing to start: insecure production configuration:\n  - "
            + "\n  - ".join(problems)
            + "\n(set ALLOW_INSECURE_WEBHOOKS=1 only for local development)"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _assert_secure_production_config()
    # Init DB first (in thread so it doesn't block the event loop), then pre-warm OpenAI
    db_task = create_tracked_task(
        asyncio.to_thread(_init_db_background), name="init_db_background"
    )

    async def _voice_cache_after_db():
        await db_task
        await _startup_prewarm_voice_caches()

    voice_cache_task = create_tracked_task(
        _voice_cache_after_db(), name="startup_voice_cache_prewarm"
    )
    warm_task = create_tracked_task(pre_warm_openai(), name="pre_warm_openai")
    keep_warm_task = create_tracked_task(keep_client_warm(), name="keep_client_warm")
    yield
    for t in (db_task, voice_cache_task, warm_task, keep_warm_task):
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
async def security_headers_middleware(request: Request, call_next):
    """Add browser hardening headers on every response (additive, non-destructive)."""
    from security.http_headers import apply_security_headers

    response = await call_next(request)
    apply_security_headers(response, request=request)
    return response


@app.middleware("http")
async def observability_webhook_timing(request: Request, call_next):
    """When OBS_TRACE_WEBHOOKS=1, log /api/phone/* and /api/sms/* latency and status."""
    return await webhook_timing_middleware(request, call_next)


@app.middleware("http")
async def db_connection_release_middleware(request: Request, call_next):
    """Return pooled DB connections after each HTTP request."""
    try:
        return await call_next(request)
    finally:
        db_release_thread_connection()


# In-memory rate limit for public webhooks (phone/SMS) — 120 req/min per IP
_webhook_rate_limit: dict = {}  # ip -> list of timestamps
_webhook_rate_limit_lock = asyncio.Lock()
WEBHOOK_RATE_LIMIT_PER_MIN = 120
WEBHOOK_RATE_LIMIT_MAX_IPS = 5000


def _rate_limit_client_ip(request: Request) -> str:
    """Per-source key for rate limiting.

    Behind Render's edge the socket peer (request.client.host) is the load
    balancer, so keying on it collapses every caller into one bucket — useless
    for isolating an abuser and liable to 429 legitimate traffic. Render sets
    the originating client as the leftmost X-Forwarded-For hop, so we use that.
    XFF is client-spoofable, but this limiter is only a coarse cost backstop;
    the authoritative gate against forged webhooks is signature validation.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


async def _webhook_rate_limit_check(request: Request) -> Optional[Response]:
    """Return 429 response if IP over limit for /api/phone/incoming or /api/sms/incoming; else None."""
    path = request.url.path
    if path not in ("/api/phone/incoming", "/api/sms/incoming"):
        return None
    ip = _rate_limit_client_ip(request)
    now = datetime.now(timezone.utc).timestamp()
    async with _webhook_rate_limit_lock:
        # Opportunistically prune stale IP buckets.
        for bucket_ip in list(_webhook_rate_limit.keys()):
            bucket = _webhook_rate_limit[bucket_ip]
            bucket[:] = [t for t in bucket if now - t < 60]
            if not bucket:
                _webhook_rate_limit.pop(bucket_ip, None)
        if len(_webhook_rate_limit) > WEBHOOK_RATE_LIMIT_MAX_IPS:
            oldest_ip = min(
                _webhook_rate_limit.items(),
                key=lambda kv: kv[1][0] if kv[1] else now,
            )[0]
            _webhook_rate_limit.pop(oldest_ip, None)
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

        payload = {
            "sessionId": "e3c6b1",
            "timestamp": __import__("time").time() * 1000,
            "location": "main.py:CORS",
            "message": "request",
            "data": data,
        }
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
        _debug_log_payload(
            {
                "method": request.method,
                "path": request.url.path,
                "origin": origin,
                "allowed_origins": allowed_origins,
            }
        )
        return await call_next(request)

    _debug_log_payload({"event": "startup", "allowed_origins": allowed_origins})

# Domain routers (strangler-fig migration out of main.py — see routers/).
from routers import health as health_router
from routers import leads as leads_router
from routers import sms_automations as sms_automations_router
from routers import cron as cron_router
from routers import provisioning as provisioning_router
from routers import admin_audit as admin_audit_router
from routers import billing as billing_router
from routers import analytics as analytics_router
from routers import appointments as appointments_router
from routers import admin as admin_router
from routers import sms as sms_router

app.include_router(health_router.router)
app.include_router(leads_router.router)
app.include_router(sms_automations_router.router)
app.include_router(cron_router.router)
app.include_router(provisioning_router.router)
app.include_router(admin_audit_router.router)
app.include_router(billing_router.router)
app.include_router(analytics_router.router)
app.include_router(appointments_router.router)
app.include_router(admin_router.router)
app.include_router(sms_router.router)

# The inbound-SMS handler + its SMS-only helpers now live in routers/sms; re-export so
# tests that inspect main.handle_incoming_sms or import _is_sms_confirmation keep working.
from routers.sms import (  # noqa: E402,F401
    handle_incoming_sms,
    _is_sms_confirmation,
    _sms_compliance_keyword,
    _staff_pending_review_sms_enabled,
    _notify_staff_pending_review,
    _maybe_handle_staff_sms_approval,
)

print(f"[INIT] Python {sys.version.split()[0]}, openai=={openai.__version__}")
sys.stdout.flush()

# The lazy OpenAI client now lives in runtime (so booking/voice/SMS modules can share
# it). Re-export `client` (a stable proxy instance) and _ensure_openai_client so main's
# many `client.…` calls and tests patching main.client keep resolving. New code outside
# main should prefer runtime.client / runtime._ensure_openai_client().
from runtime import client, _ensure_openai_client  # noqa: E402,F401


print("[INIT] Initializing Twilio...", flush=True)
# Initialize Twilio (optional - only if credentials are provided)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
TWILIO_SMS_FROM = (
    os.getenv("TWILIO_SMS_FROM") or TWILIO_PHONE_NUMBER
)  # Same or separate number for SMS

if TWILIO_AVAILABLE and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        runtime.twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        print(f"Twilio initialized successfully")
    except Exception as e:
        print(f"WARNING: Twilio initialization failed: {e}")
elif not TWILIO_AVAILABLE:
    print(
        "WARNING: Twilio not installed - phone features disabled. Install with: pip install twilio"
    )
elif not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
    print("WARNING: Twilio credentials not found - phone features will be disabled")


# Project root (parent of backend) for client configs
PROJECT_ROOT = _backend_dir.parent
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()


# Auth: Clerk JWT verification for multi-tenant
try:
    from auth import get_bearer_token, verify_clerk_token
except ImportError as e:
    raise RuntimeError("Failed to import auth module") from e

# Database: PostgreSQL when DATABASE_URL is set (production)
# Import functions eagerly (no network); init_db() is deferred to background.
# USE_DB and _db_imported live in runtime.py (read as runtime.USE_DB / runtime._db_imported).
try:
    from database import (
        init_db,
        set_request_client_id,
        _client_id as get_db_client_id,
        db_appointments_get_all,
        db_appointments_diagnostics,
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
        db_tenant_all_member_clerk_ids,
        db_tenant_get_invite_email,
        db_tenant_invite_peek,
        db_tenant_memberships_for_user,
        _normalize_invite_email,
        db_tenant_member_assign_owner,
        db_tenant_member_remove,
        db_tenant_member_set_single,
        db_tenant_membership_tenant_ids,
        db_tenant_invite_upsert,
        db_tenant_invite_delete,
        db_tenant_invite_consume,
        db_tenant_list_all,
        db_tenant_update_subscription,
        db_tenant_set_billing_exempt,
        db_tenant_extend_trial,
        db_tenant_set_twilio_phone,
        db_tenant_get_by_stripe_subscription_id,
        db_tenant_get_by_client_id,
        db_tenant_get_business_config,
        db_tenant_set_business_config,
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
        db_appointments_get_active_for_sms_context,
        db_appointments_update_active_name_by_phone,
        db_appointments_latest_identity_for_phone,
        db_appointments_resolve_for_sms,
        db_appointments_get_accepted_for_date,
        db_appointments_mark_reminder_sent,
        db_appointments_in_date_range,
        db_ping,
        db_release_thread_connection,
        db_retention_purge,
        db_export_tenant_snapshot,
        db_legal_hold_set,
        db_legal_hold_clear,
        db_legal_hold_list_active,
        db_cron_run_start,
        db_cron_run_finish,
        db_cron_runs_last_success,
        DAILY_CRON_JOBS,
        CRON_JOB_NAMES,
    )

    runtime._db_imported = True
    print("[INIT] Database module imported (connection deferred)", flush=True)
except ImportError as e:
    print(f"[WARN] Database module import failed: {e}", flush=True)

# Shared dependencies + auth helpers now live in deps.py. Re-export here so the
# many `from main import require_tenant` / `import main; main.audit_log` usages
# (routes still in main, plus the test suite) keep resolving to the same objects.
from deps import (  # noqa: E402
    audit_log,
    require_tenant,
    require_admin,
    require_active_subscription,
    _bind_tenant_db_context,
    _ensure_db_ready,
    _clerk_fetch_user_link,
    _clerk_patch_user_tenant_metadata,
    _settings_load_debug_enabled,
    _admin_access_debug_enabled,
    _admin_access_log,
)
from models import SmsAutomationCreate, SmsAutomationUpdate  # noqa: E402,F401

# Clerk linking/invites + admin access-debug snapshot now live in clerk_service;
# re-export so main's admin routes (and tests patching main._clerk_*) keep resolving.
from clerk_service import (  # noqa: E402,F401
    _clerk_api_json_list,
    _clerk_revoke_active_sessions,
    _clerk_user_ids_from_api,
    _clerk_user_ids_from_tenant_members,
    _clerk_user_ids_for_email,
    _clerk_relink_users_to_tenant,
    _clerk_invite_error_message,
    _clerk_clear_tenant_access,
    _clerk_relink_user_to_tenant,
    _clerk_link_email_to_tenant,
    _admin_tenant_access_debug_snapshot,
)

# send_sms / _phone_to_e164 now live in sms_service; re-export so the many
# `send_sms(...)` calls in main's still-unmigrated routes (and tests patching
# main.send_sms) keep resolving.
from sms_service import send_sms, _phone_to_e164, normalize_phone  # noqa: E402,F401

# Caller memory (repeat-caller recognition) now lives in caller_memory; re-export so
# main's still-resident voice/SMS code keeps resolving. New routers import caller_memory.
from caller_memory import (  # noqa: E402,F401
    get_caller_memory,
    refresh_caller_memory_for_prompt,
    update_caller_memory,
)

# Voice service (cut 1): recording-gating + phone-greeting payload. Re-export so main's
# still-resident phone/business-info/greeting-preview/recording routes (and tests that
# patch these on main) keep resolving. Owning module = voice_service.
from voice_service import (  # noqa: E402,F401
    RECORDING_DISCLOSURE_TEXT,
    DEFAULT_GREETING_TEMPLATE,
    _call_recording_env_enabled,
    _tenant_for_call_recording,
    _call_recording_enabled_for_tenant,
    _call_recording_enabled,
    _call_summary_enabled_for_tenant,
    _greeting_debug_enabled,
    _format_greeting_template,
    _resolve_greeting_business_name,
    build_phone_greeting_payload,
    _log_greeting_debug,
    # TTS synthesis + audio cache (cut 2)
    GOT_IT_PHRASE,
    ONE_MOMENT_PHRASE,
    _got_it_cache_key,
    _one_moment_cache_key,
    _synthesize_tts_clip,
    _ensure_greeting_audio_cached,
    _warm_auxiliary_voice_cache,
    warm_client_voice_cache,
    _warm_all_tenant_voice_caches,
    _warm_client_voice_cache_async,
    _warm_auxiliary_voice_cache_async,
    _greeting_audio_cache_key,
    # STT provider selection (cut 3)
    _voice_stt_use_deepgram,
    uses_non_latin_script,
    _text_looks_latin,
    _conversation_prefers_english_stt,
    # call-session context (cut 4)
    _persist_call_session,
    _merge_call_session,
    _call_sid_from_form,
    _restore_call_context,
    _get_client_id_from_call,
    # call log (cut 5)
    call_log_entries,
    CALL_LOG_MAX_ENTRIES,
    call_log_start,
    call_log_merge_recording,
    _file_call_log_merge_recording,
    call_log_set_outcome,
    call_log_end,
    # call recording: SSRF-guarded fetch + summary (cut 6)
    _is_trusted_twilio_media_url,
    _fetch_twilio_recording_bytes,
    _summarize_call_recording_sync,
    _schedule_recording_summary,
)

# Business-config loading/normalization now lives in config_service; re-export so
# main's still-resident routes and the tests that patch main.get_business_info etc.
# keep resolving.
from config_service import (  # noqa: E402,F401
    ALLOWED_BUSINESS_VERTICALS,
    BUSINESS_VERTICAL_LABELS,
    _normalize_service_entries,
    _normalize_special_entries,
    _normalize_rule_entries,
    _config_data_to_business_info,
    client_config_source,
    _read_raw_client_config,
    save_raw_client_config,
    load_client_config,
    _DEMO_BUSINESS_INFO,
    _minimal_business_info_from_tenant_dict,
    _default_business_info_for_tenant,
    business_info_for_dashboard,
    _default_client_config_data,
    get_business_info,
    get_tts_voice,
    get_tts_speed,
    get_client_data_dir,
)

# Stateless booking primitives (duration/time-format/service/staff-name/validation)
# now live in booking_service; re-export so main's still-resident booking/voice/SMS
# code (and tests patching main._X) keep resolving. Owning module = booking_service.
from booking_service import (  # noqa: E402,F401
    DEFAULT_SLOT_DURATION_MINUTES,
    _service_duration_minutes_for_reason,
    _booking_duration_minutes,
    _appointment_duration_minutes,
    _duration_minutes_for_appointment,
    _normalize_service_choice_for_booking,
    _staff_display_name_for_appointment,
    _format_appointment_details_confirmation_sms,
    _hhmm_to_ampm,
    _normalize_time_to_hhmm,
    _time_to_minutes,
    _optional_staff_id_validated,
    _appointment_email_enabled,
    # stateful slot/calendar engine (cut 2)
    _tenant_sms_from_number,
    _booked_slot_duration_by_appointment_id,
    _load_booked_slots,
    _save_booked_slots,
    _staff_slot_key,
    _staff_label_for_slot_key,
    _appointment_rows_for_calendar_merge,
    _appointment_by_id_map,
    _booked_slot_rows_that_hold_calendar,
    _get_all_booked_slots_merged,
    get_booked_slots,
    _slot_overlaps,
    _slot_blocking_details,
    is_slot_available,
    reserve_slot,
    release_slot,
    _reconcile_sms_appointment_slot_after_detail_change,
    _reconcile_booked_slots_orphans,
    _voice_calendar_holds,
    _invalidate_booked_slots_cache,
    get_booked_slots_prompt_text,
    # appointment decline/cancel SMS polish (used by the staff-SMS approval handler)
    polish_owner_customer_sms,
    polish_owner_decline_sms,
)


def _init_db_background():
    """Initialize DB connection in background thread so server starts immediately."""
    if not runtime._db_imported or not os.getenv("DATABASE_URL"):
        return
    try:
        runtime.USE_DB = init_db()
        print(f"[INIT] Database ready (runtime.USE_DB={runtime.USE_DB})", flush=True)
    except Exception as e:
        print(f"[WARN] Database init failed (using in-memory): {e}", flush=True)




def _stable_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# In-memory fallback when no database (dev / testing). Aliased to the runtime
# lists (same objects) so routers can share them via runtime.appointments/messages
# without importing main. Only mutated, never reassigned — alias stays valid.
appointments: List[dict] = runtime.appointments
messages: List[dict] = runtime.messages



def invalidate_voice_cache(client_id: Optional[str] = None) -> None:
    """Clear greeting/got-it audio cache when voice, speed, greeting, name, or receptionist changes."""
    from voice.tts_cache import invalidate_client

    if client_id:
        invalidate_client(PROJECT_ROOT, client_id)
    else:
        for d in (PROJECT_ROOT / "clients").glob("*/voice_cache"):
            if d.is_dir():
                for p in d.glob("*.mp3"):
                    try:
                        p.unlink()
                    except OSError:
                        pass
        from voice.tts_cache import clear_all_memory

        clear_all_memory()


async def _startup_prewarm_voice_caches() -> None:
    """After DB init, prewarm greeting/got-it/one-moment for provisioned tenants."""
    try:
        await asyncio.to_thread(_warm_all_tenant_voice_caches)
    except Exception as e:
        logger.warning("startup voice cache prewarm failed: %s", e)


def get_greeting_text() -> str:
    """Greeting for phone (uses client config if set)."""
    info = get_business_info()
    tenant = _tenant_for_call_recording()
    payload = build_phone_greeting_payload(info, tenant)
    _log_greeting_debug("greeting_built", payload)
    return payload["spoken_text"]


class ConversationRequest(BaseModel):
    message: str
    session_id: str
    conversation_history: Optional[List[dict]] = []


class ConversationResponse(BaseModel):
    response: str
    action: Optional[str] = None
    data: Optional[dict] = None


class MessageRequest(BaseModel):
    caller_name: str
    caller_phone: str
    message: str
    urgency: str = "normal"


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "fable"  # nova, alloy, echo, fable, onyx, shimmer
    speed: Optional[float] = None  # OpenAI 0.25–4.0; if omitted uses business config








# _validate_twilio_webhook now lives in deps (cross-cutting webhook-auth helper used by
# the SMS/phone routers and main's remaining webhook routes); re-export so the ~9 callers
# still in main and tests patching it keep resolving.
from deps import _validate_twilio_webhook  # noqa: E402,F401




def get_staff_phone_by_name(name: str) -> Optional[str]:
    """Return E.164 for a plan-authorized transfer destination by name (not the full staff roster)."""
    from staff_transfers import get_transfer_phone_by_name

    return get_transfer_phone_by_name(name, get_business_info())


def staff_on_roster(info: Optional[dict] = None) -> List[dict]:
    """Staff rows with a display name (required for calendar booking / AI roster)."""
    data = info if info is not None else get_business_info()
    out: List[dict] = []
    for s in data.get("staff") or []:
        if not isinstance(s, dict):
            continue
        name = (s.get("name") or "").strip()
        if name:
            out.append(s)
    return out


def staff_roster_ready_for_booking(info: Optional[dict] = None) -> bool:
    """True when at least one named team member is on the roster."""
    return len(staff_on_roster(info)) >= 1


def forwarding_phone_ready(info: Optional[dict] = None) -> bool:
    """True when store forwarding phone is configured for live handoffs."""
    data = info if info is not None else get_business_info()
    return bool((data.get("forwarding_phone") or "").strip())


def voice_receptionist_ready(info: Optional[dict] = None) -> bool:
    """True when both team roster and store phone are configured for full AI receptionist calls."""
    return staff_roster_ready_for_booking(info) and forwarding_phone_ready(info)


def setup_transfers_to_store_after_message(info: Optional[dict] = None) -> bool:
    """
    True when inbound calls should play the setup message then dial the store:
    store phone is set but the team roster is not ready yet.
    """
    data = info if info is not None else get_business_info()
    return forwarding_phone_ready(data) and not staff_roster_ready_for_booking(data)


def setup_not_ready_call_message(info: Optional[dict] = None) -> str:
    """Spoken when the AI receptionist is not fully configured (before optional store transfer)."""
    data = info if info is not None else get_business_info()
    roster_ok = staff_roster_ready_for_booking(data)
    phone_ok = forwarding_phone_ready(data)
    if not roster_ok and phone_ok:
        return (
            "Sorry, your AI receptionist cannot work until the owner adds team members "
            "to their roster online. I will transfer you to the store now."
        )
    if not roster_ok and not phone_ok:
        return (
            "Sorry, I won't be able to function until the owner updates their settings online, "
            "including team members on the roster and a store phone number."
        )
    if not phone_ok:
        return (
            "Sorry, I won't be able to function until the owner adds a store phone number "
            "and completes their setup online."
        )
    return ""


def _normalize_dial_number(forwarding_phone: str) -> str:
    clean = "".join(c for c in (forwarding_phone or "") if c.isdigit() or c == "+")
    if not clean.startswith("+"):
        if len(clean) == 10:
            clean = f"+1{clean}"
        elif len(clean) == 11 and clean.startswith("1"):
            clean = f"+{clean}"
        else:
            clean = f"+1{clean}"
    return clean


def append_dial_forwarding_only(response: VoiceResponse, forwarding_phone: str) -> None:
    """Dial the store after a custom message (no extra 'please hold' TTS)."""
    clean_phone = _normalize_dial_number(forwarding_phone)
    voice_trace("dial_forwarding_only", dial_to=mask_phone(clean_phone))
    response.dial(clean_phone, timeout=30, record=False)
    response.say(
        "I'm sorry, no one is available right now. Please try again later or leave a message.",
        voice="alice",
    )
    response.hangup()


def twiml_setup_not_ready_handoff(
    base_url: str, biz_info: dict, call_sid: str = ""
) -> VoiceResponse:
    """
    Play setup-not-ready message. Transfer to the store only when store phone is set but roster is not
    (roster-only gap). If store phone is missing, end the call after the message.
    """
    response = VoiceResponse()
    message = setup_not_ready_call_message(biz_info)
    if message:
        msg_encoded = quote(message)
        response.play(
            f"{base_url}/api/phone/tts-audio?text={msg_encoded}&voice={get_tts_voice()}"
        )
    forwarding_phone = (biz_info.get("forwarding_phone") or "").strip()
    if setup_transfers_to_store_after_message(biz_info) and forwarding_phone:
        append_dial_forwarding_only(response, forwarding_phone)
        if call_sid:
            call_log_set_outcome(call_sid, "forwarded")
    else:
        response.say(
            "Please ask the business to complete their setup online. Goodbye.",
            voice="alice",
        )
        response.hangup()
        if call_sid:
            call_log_set_outcome(call_sid, "error")
    return response


def twiml_roster_not_ready_handoff(
    base_url: str, biz_info: dict, call_sid: str = ""
) -> VoiceResponse:
    """Backward-compatible alias for setup-not-ready handoff TwiML."""
    return twiml_setup_not_ready_handoff(base_url, biz_info, call_sid=call_sid)


def parse_transfer_to(ai_text: str) -> Optional[str]:
    """If AI responded with TRANSFER_TO: Name, return the name; else None."""
    if not ai_text:
        return None
    t = ai_text.strip()
    prefix = "TRANSFER_TO:"
    if t.upper().startswith(prefix):
        return t[len(prefix) :].strip()
    return None


# Call log (Pro analytics): in-memory index by call_sid, persisted to JSON
# Booking-creation flow (voice/SMS-adjacent; the slot/calendar engine lives in booking_service).
def _phones_match_for_booking(a: str, b: str) -> bool:
    da = normalize_phone(a or "")
    db = normalize_phone(b or "")
    if not da or not db:
        return not da and not db
    return da == db or da.endswith(db[-10:]) or db.endswith(da[-10:])


def _supersede_pending_customer_drafts_for_slot(
    date: str,
    time: str,
    staff_id: Optional[str],
    *,
    client_id: Optional[str] = None,
    phone: Optional[str] = None,
) -> int:
    """
    Cancel stale voice bookings for this slot so the same caller can rebook after a failed flow.
    - pending_customer: unconfirmed draft (slot not held until SMS YES).
    - pending_review: same caller + receptionist source — frees a held slot when they call again.
    """
    if not runtime.USE_DB:
        return 0
    cid = (client_id or "").strip() or get_db_client_id()
    if not cid:
        return 0
    want_staff = _staff_slot_key(staff_id)
    norm_time = _normalize_time_to_hhmm(time) or time
    cancelled = 0
    for apt in _appointment_rows_for_calendar_merge():
        st = apt.get("status") or ""
        if st not in ("pending_customer", "pending_review"):
            continue
        if st == "pending_review":
            if (apt.get("source") or "").strip() != "receptionist":
                continue
            if not phone or not _phones_match_for_booking(
                phone, apt.get("phone") or ""
            ):
                continue
        if (apt.get("date") or "") != date:
            continue
        apt_time = _normalize_time_to_hhmm(apt.get("time") or "") or (
            apt.get("time") or ""
        )
        if apt_time != norm_time:
            continue
        if _staff_slot_key(apt.get("staff_id")) != want_staff:
            continue
        if phone and not _phones_match_for_booking(phone, apt.get("phone") or ""):
            continue
        aid = apt.get("id")
        if not aid:
            continue
        try:
            db_appointments_update(int(aid), status="cancelled", client_id=cid)
            release_slot(int(aid))
            cancelled += 1
        except Exception as e:
            logger.warning("supersede_voice_booking_draft failed apt_id=%s: %s", aid, e)
    if cancelled:
        _invalidate_booked_slots_cache()
        system_info(
            "voice_booking_draft_superseded",
            count=cancelled,
            date=date,
            time=norm_time,
            client_id=cid,
        )
    return cancelled


def _suggests_booking(text: str) -> bool:
    """True if the message suggests the caller wants to book/appointment/reservation."""
    if not text or len(text.strip()) < 2:
        return False
    t = text.lower()
    return any(
        k in t
        for k in (
            "book",
            "appointment",
            "reservation",
            "reserve",
            "schedule",
            "available",
            "slot",
            "time for",
        )
    )


_STYLIST_NO_PREF_PHRASES = (
    "anyone",
    "any stylist",
    "any one",
    "no preference",
    "no pref",
    "don't care",
    "doesn't matter",
    "whoever",
    "first available",
    "any available",
    "no particular",
    "you choose",
    "surprise me",
)


def _conversation_user_text(conversation_history: Optional[list]) -> str:
    if not conversation_history:
        return ""
    parts = [
        (m.get("content") or "").strip()
        for m in conversation_history
        if (m.get("role") or "").strip() == "user"
    ]
    return " ".join(p for p in parts if p)


def _caller_indicated_stylist_choice(
    user_text: str, info: Optional[dict] = None
) -> bool:
    t = (user_text or "").lower()
    if not t.strip():
        return False
    if any(p in t for p in _STYLIST_NO_PREF_PHRASES):
        return True
    for s in (info or get_business_info()).get("staff") or []:
        name = (s.get("name") or "").strip()
        if not name:
            continue
        nl = name.lower()
        if len(name) == 1 and nl == "a":
            # Avoid "book a haircut" — only stylist-context uses of the name A.
            if re.search(
                r"\b(with|stylist|see|prefer|choose)\s+a\b|\ba\s+(please|for|at)\b", t
            ):
                return True
            continue
        if re.search(rf"\b{re.escape(nl)}\b", t):
            return True
    return False


def _caller_indicated_service_choice(
    user_text: str, info: Optional[dict] = None
) -> bool:
    biz = info or get_business_info()
    services = _normalize_service_entries(biz.get("services") or [])
    if not services:
        return True
    t = (user_text or "").lower()
    if not t.strip():
        return False
    for s in services:
        nm = (s.get("name") or "").strip()
        if not nm:
            continue
        nml = nm.lower()
        if nml in t or re.search(rf"\b{re.escape(nml)}\b", t):
            return True
    return False


def _staff_choice_required(info: Optional[dict] = None) -> bool:
    biz = info or get_business_info()
    names = [
        (s.get("name") or "").strip()
        for s in (biz.get("staff") or [])
        if (s.get("name") or "").strip()
    ]
    return len(names) >= 2


def _conversation_suggests_booking(conversation_history: Optional[list]) -> bool:
    for m in conversation_history or []:
        if (m.get("role") or "").strip() == "user" and _suggests_booking(
            m.get("content") or ""
        ):
            return True
    return False


def _count_booking_user_turns(conversation_history: Optional[list]) -> int:
    return sum(
        1
        for m in (conversation_history or [])
        if (m.get("role") or "").strip() == "user" and (m.get("content") or "").strip()
    )


def _voice_booking_nudge_message(
    conversation_history: list, info: Optional[dict] = None
) -> Optional[str]:
    """Inject during booking if GPT has not emitted BOOKING: yet."""
    biz = info or get_business_info()
    if not _conversation_suggests_booking(conversation_history):
        return None
    turns = _count_booking_user_turns(conversation_history)
    user_text = _conversation_user_text(conversation_history)

    last_user = latest_user_message(conversation_history)
    if last_user and caller_message_suggests_pricing(last_user):
        return (
            "BOOKING REMINDER: Caller asked about price or cost. This is a normal business question—not off-topic. "
            "Answer briefly using the dollar amounts in the Services menu in your system prompt; "
            "speak naturally (e.g. a long cut runs around fifty dollars). "
            "Do NOT say you are not sure or deflect to booking without giving the price when it is listed. "
            "After answering, invite them to continue scheduling if they were booking."
        )

    if _staff_choice_required(biz) and not _caller_indicated_stylist_choice(
        user_text, biz
    ):
        if turns >= 2:
            return (
                f"BOOKING REMINDER: This caller wants an appointment ({turns} user turns). "
                "You have NOT confirmed a stylist yet. Ask ONE short question: which stylist "
                "they prefer (or anyone is fine). Do NOT ask which service yet—after they choose "
                "a stylist, offer only that person's services from the roster."
            )
        return None

    if turns < 3:
        return None

    services = _normalize_service_entries(biz.get("services") or [])
    ctx = booking_context_from_business(biz)
    if services and not service_choice_resolved(conversation_history, ctx):
        if assistant_asked_service_recently(conversation_history):
            return None
        return (
            f"BOOKING REMINDER: This caller wants an appointment after {turns} turns. "
            "Ask ONE short question: which service from the menu (only services their stylist provides). "
            "When name, date, time, service, and stylist are confirmed, you MUST output BOOKING: on this turn. "
            "Never tell the caller they are booked until BOOKING is output."
        )
    return (
        f"BOOKING REMINDER: After {turns} turns you have enough details. "
        "Output BOOKING: name|phone|email|date|time|reason|staff on this turn. "
        "Never say the appointment is confirmed until BOOKING is output."
    )


def _ai_implies_committed_booking(ai_text: str) -> bool:
    t = (ai_text or "").lower()
    if not t:
        return False
    return any(
        p in t
        for p in (
            "you're all set",
            "you are all set",
            "all set for",
            "you're booked",
            "you are booked",
            "i've booked",
            "i have booked",
            "have you scheduled",
            "you're scheduled",
            "you are scheduled",
            "i have you scheduled",
            "we have you scheduled",
            "got you scheduled",
            "got you down",
            "appointment is confirmed",
            "you're confirmed",
            "you are confirmed",
            "booking is confirmed",
            "see you then",
            "see you tomorrow",
            "see you at",
            "we'll see you",
            "we will see you",
        )
    )


def _should_attempt_voice_booking_extraction(
    conversation_history: Optional[list], ai_text: str
) -> bool:
    """Retry BOOKING: extraction when the model spoke like it booked but omitted the marker."""
    if not _conversation_suggests_booking(conversation_history):
        return False
    if not staff_roster_ready_for_booking(get_business_info()):
        return False
    turns = _count_booking_user_turns(conversation_history)
    if turns < 3:
        return False
    if _ai_implies_committed_booking(ai_text or ""):
        return True
    t = (ai_text or "").lower()
    if any(
        p in t
        for p in (
            "scheduled",
            "see you",
            "tomorrow at",
            "today at",
            " at 3",
            " at 2",
            " at 1",
            " at 4",
            " at 5",
        )
    ):
        return True
    return turns >= 4


def _extract_booking_line_from_conversation(
    conversation_history: list,
    *,
    caller_memory: Optional[dict] = None,
) -> Optional[dict]:
    """Second GPT pass: emit BOOKING: line only from agreed transcript details."""
    biz = get_business_info()
    today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    tomorrow_str = (today + timedelta(days=1)).isoformat()
    staff_names = [
        (s.get("name") or "").strip()
        for s in (biz.get("staff") or [])
        if (s.get("name") or "").strip()
    ]
    service_names = [
        (s.get("name") or "").strip()
        for s in _normalize_service_entries(biz.get("services") or [])
        if (s.get("name") or "").strip()
    ]
    mem_name = ((caller_memory or {}).get("name") or "").strip()
    transcript = "\n".join(
        f"{(m.get('role') or '').strip().upper()}: {(m.get('content') or '').strip()}"
        for m in (conversation_history or [])[-14:]
        if (m.get("content") or "").strip()
    )
    if not transcript.strip():
        return None
    sys = (
        "Extract appointment details from this phone transcript. "
        f"Today is {today_str}, tomorrow is {tomorrow_str}. "
        "If caller name, date, and time are all clearly agreed, reply with EXACTLY one line:\n"
        "BOOKING: name|phone|email|date|time|reason|staff\n"
        "Field order is FIXED: (1) caller name, (2) phone, (3) email, (4) date YYYY-MM-DD, "
        "(5) time HH:MM 24h e.g. 15:00 for 3 PM — NEVER put a stylist name in the time field, "
        "(6) service/reason from menu, (7) stylist name.\n"
        "Leave phone and email empty. reason=exact service from menu if known. "
        "staff=stylist name if chosen.\n"
        f"Staff: {', '.join(staff_names) or 'none'}. "
        f"Services: {', '.join(service_names) or 'any'}.\n"
        f"Caller name on file: {mem_name or 'unknown'}.\n"
        "If name, date, or time is missing or ambiguous, reply with exactly: NONE"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": transcript},
            ],
            temperature=0,
            max_tokens=120,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("voice_booking_extraction_failed: %s", e)
        return None
    if not raw or raw.upper().startswith("NONE"):
        return None
    parsed = parse_booking(raw)
    if not parsed:
        return None
    biz = get_business_info()
    ctx = booking_context_from_business(biz)
    prepared, repairs, reject = normalize_and_validate_booking(parsed, ctx)
    if reject:
        system_info(
            "voice_booking_extraction_rejected",
            reason=reject,
            repairs=repairs or None,
        )
        return None
    if repairs:
        system_info("voice_booking_extraction_repaired", repairs=repairs)
    return prepared


def _prepare_parsed_booking(
    booking: dict,
    *,
    info: Optional[dict] = None,
    caller_memory: Optional[dict] = None,
) -> tuple[Optional[dict], list[str], Optional[str]]:
    """Sanitize and validate date/time on a parsed BOOKING payload."""
    _apply_booking_customer_name(booking, caller_memory=caller_memory, info=info)
    ctx = booking_context_from_business(info or get_business_info())
    return normalize_and_validate_booking(booking, ctx)


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


def _staff_name_set(info: Optional[dict] = None) -> set[str]:
    biz = info or get_business_info()
    return {
        (s.get("name") or "").strip().lower()
        for s in (biz.get("staff") or [])
        if (s.get("name") or "").strip()
    }


def _caller_memory_name_usable(mem_name: str, staff_names: set[str]) -> bool:
    n = (mem_name or "").strip()
    if len(n) < 2:
        return False
    low = n.lower()
    if low in staff_names or low in ("there", "caller", "customer", "guest"):
        return False
    return True


def _apply_booking_customer_name(
    booking: dict,
    *,
    caller_memory: Optional[dict] = None,
    info: Optional[dict] = None,
) -> None:
    """Ensure BOOKING field 1 is the caller's name, not a stylist from the roster."""
    biz = info or get_business_info()
    staff_names = _staff_name_set(biz)
    name = (booking.get("name") or "").strip()
    staff_frag = (booking.get("staff") or "").strip()
    mem_name = ((caller_memory or {}).get("name") or "").strip()
    mem_ok = _caller_memory_name_usable(mem_name, staff_names)

    if name and staff_names and name.lower() in staff_names:
        booking["name"] = mem_name if mem_ok else ""
        return

    if (
        name
        and staff_frag
        and name.lower() == staff_frag.lower()
        and staff_frag.lower() in staff_names
    ):
        booking["name"] = mem_name if mem_ok else ""
        return

    if not name and mem_ok:
        booking["name"] = mem_name


def _validate_booking_requirements(
    booking: dict,
    info: Optional[dict] = None,
    *,
    conversation_history: Optional[list] = None,
) -> tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Validate required stylist/service when configured.
    Returns: (ok, fail_message, staff_id, canonical_service_name)
    """
    biz = info or get_business_info()
    user_text = _conversation_user_text(conversation_history)
    staff_rows = [s for s in (biz.get("staff") or []) if (s.get("name") or "").strip()]
    staff_id = resolve_staff_id_from_booking_fragment(booking.get("staff"))
    staff_name = ""
    if staff_id:
        for s in staff_rows:
            if (s.get("id") or "").strip() == staff_id:
                staff_name = (s.get("name") or "").strip()
                break
    if staff_rows and not staff_id:
        no_pref = any(p in user_text.lower() for p in _STYLIST_NO_PREF_PHRASES)
        if not (_caller_indicated_stylist_choice(user_text, biz) and no_pref):
            choices = ", ".join(
                (s.get("name") or "").strip()
                for s in staff_rows[:5]
                if (s.get("name") or "").strip()
            )
            msg = (
                "Absolutely — which stylist would you like to see?"
                + (f" We currently have {choices}." if choices else "")
                + " You can also say anyone if you have no preference."
            )
            return False, msg, None, None
    if (
        staff_id
        and _staff_choice_required(biz)
        and not _caller_indicated_stylist_choice(user_text, biz)
    ):
        choices = ", ".join(
            (s.get("name") or "").strip()
            for s in staff_rows[:5]
            if (s.get("name") or "").strip()
        )
        msg = (
            "Before I lock this in, which stylist would you like?"
            + (f" We have {choices}." if choices else "")
            + " Or say anyone if you have no preference."
        )
        return False, msg, None, None
    service_name, service_required = _normalize_service_choice_for_booking(
        booking.get("reason"), biz
    )
    booking_date = (booking.get("date") or "").strip()
    if booking_date:
        try:
            from business_hours import is_past_closing_for_date, same_day_after_hours_message

            target = date.fromisoformat(booking_date)
            if is_past_closing_for_date(biz, target):
                return False, same_day_after_hours_message(biz), staff_id, None
        except ValueError:
            pass
    if service_required and not service_name:
        service_choices = ", ".join(
            (s.get("name") or "").strip()
            for s in _normalize_service_entries(biz.get("services") or [])[:5]
            if (s.get("name") or "").strip()
        )
        ctx = booking_context_from_business(biz)
        msg = service_prompt_message(
            staff_name=staff_name,
            service_choices=service_choices,
            already_asked=assistant_asked_service_recently(conversation_history),
        )
        return False, msg, staff_id, None
    ctx = booking_context_from_business(biz)
    if service_required and service_name and not service_choice_resolved(
        conversation_history, ctx, canonical_service=service_name
    ):
        service_choices = ", ".join(
            (s.get("name") or "").strip()
            for s in _normalize_service_entries(biz.get("services") or [])[:5]
            if (s.get("name") or "").strip()
        )
        msg = service_prompt_message(
            staff_name=staff_name,
            service_choices=service_choices,
            already_asked=assistant_asked_service_recently(conversation_history),
        )
        return False, msg, staff_id, None
    return True, None, staff_id, service_name


def _create_appointment_from_booking(
    booking: dict,
    client_id_override: Optional[str] = None,
    reserve_slot_immediately: bool = True,
    caller_memory: Optional[dict] = None,
) -> Optional[dict]:
    """Create appointment from parsed BOOKING; check slot; return appointment_data or None (slot taken).
    Pass client_id_override from voice flow so appointment is stored under correct tenant (async task may not have context).
    When reserve_slot_immediately is False (voice), the row is created as pending_customer but the calendar slot
    is only reserved after the customer SMS-confirms (see handle_incoming_sms)."""
    date = (booking.get("date") or "").strip()
    time_raw = (booking.get("time") or "").strip()
    ctx = booking_context_from_business(get_business_info())
    time = normalize_booking_time(time_raw) or ""
    if not is_valid_booking_date(date) or not looks_like_booking_time(time, ctx):
        return None
    _apply_booking_customer_name(booking, caller_memory=caller_memory)
    name = (booking.get("name") or "").strip()
    if not name or not date or not time:
        return None
    cid_for_slot = (client_id_override or "").strip() or get_db_client_id()
    if cid_for_slot:
        set_request_client_id(cid_for_slot)
    staff_key = resolve_staff_id_from_booking_fragment(booking.get("staff"))
    canonical_service, _ = _normalize_service_choice_for_booking(booking.get("reason"))
    if canonical_service:
        booking["reason"] = canonical_service
    duration_min = _booking_duration_minutes(booking)
    _supersede_pending_customer_drafts_for_slot(
        date,
        time,
        staff_key,
        client_id=cid_for_slot,
        phone=(booking.get("phone") or "").strip(),
    )
    if not is_slot_available(date, time, duration_min, staff_key):
        _invalidate_booked_slots_cache()  # Next prompt build will see slot as taken
        blockers = _slot_blocking_details(
            date, time, duration_min, staff_key
        )
        system_info(
            "booking_create_failed_slot_taken",
            name=name,
            date=date,
            time=time,
            client_id=cid_for_slot,
            blocking=blockers,
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
    if runtime.USE_DB:
        row = db_appointments_insert(appointment_data)
        apt_id = row["id"]
    else:
        apt_id = len(appointments) + 1
        appointment_data["id"] = apt_id
        appointment_data["created_at"] = datetime.now().isoformat()
        appointments.append(appointment_data)
    if reserve_slot_immediately:
        reserve_slot(date, time, apt_id, duration_min, staff_key)
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


def get_twilio_language_code(language_name: str) -> str:
    """
    Map language name to Twilio language code for speech recognition.
    Returns Twilio language code (e.g., 'es-ES', 'en-US', 'hi-IN').
    Defaults to 'en-US' if language not supported.
    """
    lang = language_name
    if lang is None or (isinstance(lang, str) and not lang.strip()):
        lang = "English"
    elif not isinstance(lang, str):
        lang = str(lang)
    language_map = {
        "English": "en-US",
        "Spanish": "es-ES",
        "French": "fr-FR",
        "German": "de-DE",
        "Italian": "it-IT",
        "Portuguese": "pt-PT",
        "Chinese": "zh-CN",
        "Japanese": "ja-JP",
        "Korean": "ko-KR",
        "Hindi": "hi-IN",
        "Punjabi": "pa-IN",  # Punjabi (Gurmukhi)
        "Arabic": "ar-SA",
        "Russian": "ru-RU",
        "Dutch": "nl-NL",
        "Polish": "pl-PL",
        "Turkish": "tr-TR",
        "Swedish": "sv-SE",
        "Norwegian": "nb-NO",
        "Danish": "da-DK",
        "Finnish": "fi-FI",
        "Greek": "el-GR",
        "Czech": "cs-CZ",
        "Romanian": "ro-RO",
        "Hungarian": "hu-HU",
        "Thai": "th-TH",
        "Vietnamese": "vi-VN",
        "Indonesian": "id-ID",
        "Malay": "ms-MY",
    }

    # Try exact match first
    if lang in language_map:
        return language_map[lang]

    # Try case-insensitive match
    for key, code in language_map.items():
        if key.lower() == lang.lower():
            return code

    # Default to English if not found
    return "en-US"


async def generate_response_async(
    call_sid: str, call_data: dict, detected_lang: str, base_url: str
):
    """
    Background task to generate GPT response and TTS audio.
    Updates response_status when ready.
    """
    try:
        # Keep tenant context so SMS and DB use correct client_id (async runs outside request)
        set_request_client_id(call_data.get("client_id") or get_db_client_id())
        fn_refresh = (call_data.get("from_number") or "").strip()
        if fn_refresh:
            call_data["caller_memory"] = refresh_caller_memory_for_prompt(
                fn_refresh, call_data.get("client_id")
            )
        voice_info(
            "generate_response_start",
            call_sid=call_sid,
            from_number=call_data.get("from_number") or None,
            client_id=call_data.get("client_id") or None,
        )

        # Always include booked slots (skip cache so prompt and is_slot_available see same data—avoids "available" then "booked")
        messages = [
            {
                "role": "system",
                "content": get_system_prompt(
                    detected_lang,
                    call_data.get("caller_memory"),
                    include_booked_slots=True,
                    skip_slots_cache=True,
                ),
            }
        ]
        messages.extend(call_data["conversation_history"])
        nudge = _voice_booking_nudge_message(call_data["conversation_history"])
        if nudge:
            messages.append({"role": "system", "content": nudge})
            voice_info(
                "voice_booking_nudge_injected",
                call_sid=call_sid,
                client_id=str(call_data.get("client_id") or ""),
                user_turns=_count_booking_user_turns(call_data["conversation_history"]),
            )

        ai_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.8,
            max_tokens=200,
            stream=False,
        )

        ai_text = ai_response.choices[0].message.content
        voice_debug("gpt_reply", call_sid=call_sid, reply_preview=(ai_text or "")[:80])
        booking = parse_booking(ai_text)
        if booking:
            booking, repairs, reject = _prepare_parsed_booking(
                booking,
                caller_memory=call_data.get("caller_memory"),
            )
            if reject:
                system_info(
                    "voice_booking_line_rejected",
                    call_sid=call_sid,
                    reason=reject,
                    repairs=repairs or None,
                )
                booking = None
            elif repairs:
                system_info(
                    "voice_booking_line_repaired",
                    call_sid=call_sid,
                    repairs=repairs,
                )
        if not booking and _should_attempt_voice_booking_extraction(
            call_data.get("conversation_history"), ai_text or ""
        ):
            extracted = await asyncio.to_thread(
                _extract_booking_line_from_conversation,
                call_data.get("conversation_history") or [],
                caller_memory=call_data.get("caller_memory"),
            )
            if extracted:
                booking = extracted
                voice_info(
                    "voice_booking_extracted_retry",
                    call_sid=call_sid,
                    client_id=str(call_data.get("client_id") or ""),
                )
        # BOOKING: create appointment from AI output if present; replace response with confirmation or slot-taken message
        if booking:
            fail_msg = None
            if not staff_roster_ready_for_booking():
                ai_text = (
                    "I'm not able to book appointments until the business adds team members to their roster online. "
                    "Let me connect you with the store."
                )
            else:
                try:
                    from_num = call_data.get("from_number") or ""
                    to_num = call_data.get("to_number") or ""
                    cid_raw = call_data.get("client_id") or ""
                    from observability import name_initial_for_log

                    system_info(
                        "voice_booking_line_parsed",
                        name_initial=name_initial_for_log(booking.get("name")),
                        date=booking.get("date"),
                        time=booking.get("time"),
                        from_number=from_num or None,
                        to_number=to_num or None,
                        client_id=cid_raw or None,
                    )
                    # Use caller's phone from Twilio when available (don't require asking)
                    if from_num:
                        booking["phone"] = (
                            booking.get("phone") or ""
                        ).strip() or from_num
                    cid = (call_data.get("client_id") or "").strip() or None
                    ok_booking, fail_msg, _, canonical_service = (
                        _validate_booking_requirements(
                            booking,
                            conversation_history=call_data.get("conversation_history"),
                        )
                    )
                    if not ok_booking:
                        ai_text = (
                            fail_msg
                            or "I need your stylist and service before I can book that."
                        )
                        apt = None
                    else:
                        if canonical_service:
                            booking["reason"] = canonical_service
                        apt = _create_appointment_from_booking(
                            booking,
                            client_id_override=cid,
                            reserve_slot_immediately=False,
                            caller_memory=call_data.get("caller_memory"),
                        )
                    if apt:
                        call_data["appointment_created"] = True
                        if not (apt.get("phone") or "").strip() and call_data.get(
                            "from_number"
                        ):
                            apt["phone"] = call_data["from_number"]
                            if runtime.USE_DB and apt.get("id"):
                                try:
                                    db_appointments_update(
                                        apt["id"], phone=apt["phone"]
                                    )
                                except Exception:
                                    pass
                        thanks_msg = _format_appointment_details_confirmation_sms(apt)
                        to_number_sms = (
                            (call_data.get("from_number") or "").strip()
                            or (apt.get("phone") or "").strip()
                            or ""
                        )
                        from_number_sms = (
                            call_data.get("to_number") or ""
                        ).strip() or None
                        if not from_number_sms and cid and runtime.USE_DB:
                            tenant_row = db_tenant_get_by_client_id(cid)
                            if tenant_row:
                                from_number_sms = (
                                    tenant_row.get("twilio_phone_number") or ""
                                ).strip()
                                sms_info(
                                    "confirmation_sms_from_tenant_lookup", client_id=cid
                                )
                            else:
                                sms_info(
                                    "confirmation_sms_tenant_missing_for_from_override",
                                    client_id=cid,
                                )
                        if not from_number_sms:
                            from_number_sms = _tenant_sms_from_number()
                        sms_info(
                            "post_booking_confirmation_dispatch",
                            client_id=cid,
                            to_set=bool(to_number_sms),
                            from_set=bool(from_number_sms),
                        )
                        if to_number_sms:
                            ok = send_sms(
                                to_number_sms,
                                thanks_msg,
                                from_override=from_number_sms or None,
                            )
                            sms_info(
                                "post_booking_confirmation_sms",
                                client_id=cid,
                                to_number=to_number_sms,
                                from_number=from_number_sms,
                                success=ok,
                            )
                            if ok:
                                if runtime.USE_DB and cid and apt.get("id"):
                                    try:
                                        db_sms_session_upsert(
                                            to_number_sms,
                                            cid,
                                            [
                                                {
                                                    "role": "assistant",
                                                    "content": (
                                                        "Appointment details sent by text. "
                                                        "Reply YES or CONFIRM when everything looks right."
                                                    ),
                                                }
                                            ],
                                            int(apt["id"]),
                                        )
                                        sms_info(
                                            "post_booking_sms_session_linked",
                                            client_id=cid,
                                            apt_id=apt.get("id"),
                                        )
                                    except Exception as sess_err:
                                        logger.warning(
                                            "post_booking_sms_session_link_failed apt_id=%s: %s",
                                            apt.get("id"),
                                            sess_err,
                                            exc_info=True,
                                        )
                                ai_text = (
                                    "I've texted you the details. Please check your phone and reply YES or CONFIRM when everything looks right—that locks the time and sends your request to the shop. "
                                    "The time is not finalized until you confirm by text."
                                )
                            else:
                                ai_text = "Your visit request is saved. We could not send the confirmation text from this line right now—please text YES to this business number from your mobile when you're ready to confirm, or call us back."
                        else:
                            sms_info(
                                "post_booking_confirmation_skipped",
                                reason="no_caller_phone",
                                client_id=cid,
                            )
                            ai_text = "We've saved your booking request. We don't have a mobile number on this call to text you—please call back or text us from your phone with YES to confirm."
                        fn_mem = (call_data.get("from_number") or "").strip()
                        if fn_mem:
                            dp = {
                                "last_voice_booking_date": apt.get("date"),
                                "last_voice_booking_time": apt.get("time"),
                                "last_service": (
                                    (apt.get("reason") or "").strip()[:120] or None
                                ),
                            }
                            em_patch = (apt.get("email") or "").strip()
                            if em_patch:
                                dp["email_on_file"] = em_patch
                            dp = {k: v for k, v in dp.items() if v}
                            try:
                                update_caller_memory(
                                    fn_mem,
                                    name=(apt.get("name") or "").strip() or None,
                                    last_reason="appointment details texted (pending SMS confirmation)",
                                    increment_count=False,
                                    data_patch=dp if dp else None,
                                )
                                if call_sid:
                                    _merge_call_session(
                                        call_sid,
                                        {
                                            "caller_memory": get_caller_memory(
                                                fn_mem
                                            )
                                        },
                                    )
                            except Exception:
                                pass
                    else:
                        ctx = booking_context_from_business(get_business_info())
                        name_ok = bool((booking.get("name") or "").strip())
                        date_ok = is_valid_booking_date(booking.get("date"))
                        time_ok = looks_like_booking_time(booking.get("time"), ctx)
                        if fail_msg:
                            reason = "missing_required_booking_fields"
                        else:
                            reason = (
                                "slot_taken"
                                if (name_ok and date_ok and time_ok)
                                else ("no_name" if not name_ok else "no_date_time")
                            )
                        system_info(
                            "voice_booking_not_created",
                            reason=reason,
                            name_ok=name_ok,
                            date_ok=date_ok,
                            time_ok=time_ok,
                        )
                        if fail_msg:
                            ai_text = fail_msg
                        elif not name_ok:
                            ai_text = "I'd love to book that for you—what's your name?"
                        elif not date_ok or not time_ok:
                            ai_text = "I need the date and time again to confirm—which day and time would you like?"
                        else:
                            ai_text = "That time slot just got booked. Would you like to try another time or another day?"
                except Exception as e:
                    logger.exception(
                        "voice_booking_or_sms_failed call_sid=%s: %s", call_sid, e
                    )
                    ai_text = "We've got your request. If you don't get a confirmation text in a moment, please call back—we'll have your details."
        elif _conversation_suggests_booking(call_data.get("conversation_history")):
            user_turns = _count_booking_user_turns(
                call_data.get("conversation_history")
            )
            if user_turns >= 2:
                system_info(
                    "voice_booking_intent_no_marker",
                    call_sid=call_sid,
                    client_id=str(call_data.get("client_id") or ""),
                    user_turns=user_turns,
                    reply_len=len(ai_text or ""),
                )
            call_data["booking_intent"] = True

        if (
            not booking
            and not call_data.get("appointment_created")
            and _ai_implies_committed_booking(ai_text or "")
        ):
            system_info(
                "voice_booking_false_verbal_confirm",
                call_sid=call_sid,
                client_id=str(call_data.get("client_id") or ""),
            )
            ai_text = (
                "I'm still putting your visit together—I haven't locked in the time yet. "
                "Let me confirm the details with you first, then I'll text you to confirm."
            )

        # Never send BOOKING: machine line to TTS or conversation history
        ai_text = _strip_booking_directive_for_voice(ai_text or "")
        if not ai_text:
            ai_text = "Thanks—we've noted that. Let us know if you need anything else."

        # Add AI response to conversation
        ai_message = {"role": "assistant", "content": ai_text}
        call_data["conversation_history"].append(ai_message)
        _persist_call_session(call_sid, call_data)

        # Pro: Staff transfer - AI may respond with TRANSFER_TO: Name
        transfer_name = parse_transfer_to(ai_text)
        if transfer_name:
            staff_phone = get_staff_phone_by_name(transfer_name)
            if staff_phone:
                voice_forward(
                    "staff_transfer_by_name",
                    call_sid=call_sid,
                    client_id=str(call_data.get("client_id") or ""),
                    forward_kind="staff_named",
                    staff_name=transfer_name,
                )
                call_data["outcome"] = "forwarded"
                call_log_set_outcome(call_sid, "forwarded")
                response_status[call_sid] = {
                    "status": "forward",
                    "audio_url": None,
                    "ai_text": ai_text,
                    "forwarding_phone": staff_phone,
                }
                return
            voice_warning(
                "staff_transfer_name_not_found",
                call_sid=call_sid,
                client_id_prefix=str(call_data.get("client_id") or "")[:12],
                staff_name=transfer_name[:80],
            )

        # Check if user wants to talk to a real person - forward if needed
        if should_forward_to_human(
            "",
            ai_text,
            call_sid=call_sid,
            client_id=str(call_data.get("client_id") or ""),
        ):
            forwarding_phone = get_business_info().get("forwarding_phone")
            if forwarding_phone:
                voice_forward(
                    "ai_transfer_intent_in_reply",
                    call_sid=call_sid,
                    client_id=str(call_data.get("client_id") or ""),
                    forward_kind="fallback",
                    has_fallback_configured=True,
                )
                call_data["outcome"] = "forwarded"
                call_log_set_outcome(call_sid, "forwarded")
                response_status[call_sid] = {
                    "status": "forward",
                    "audio_url": None,
                    "ai_text": ai_text,
                    "forwarding_phone": forwarding_phone,
                }
                return

        # Generate TTS audio URL
        ai_text_encoded = quote(ai_text)
        tts_audio_url = f"{base_url}/api/phone/tts-audio?text={ai_text_encoded}&voice={get_tts_voice()}"

        # Mark as ready
        response_status[call_sid] = {
            "status": "ready",
            "audio_url": tts_audio_url,
            "ai_text": ai_text,
        }
        voice_call_phase(
            "gpt_response_ready",
            call_sid=call_sid,
            client_id=str(call_data.get("client_id") or ""),
            reply_len=len(ai_text or ""),
        )

    except Exception as e:
        voice_warning(
            "gpt_response_failed",
            call_sid=call_sid,
            client_id_prefix=str(call_data.get("client_id") or "")[:12],
            error_type=type(e).__name__,
        )
        logger.exception("generate_response_async failed call_sid=%s", call_sid)
        # Graceful fallback: play fallback message so caller does not get dead air
        fallback_encoded = quote(TTS_FALLBACK_TEXT)
        fallback_tts_url = f"{base_url}/api/phone/tts-audio?text={fallback_encoded}&voice={get_tts_voice()}"
        response_status[call_sid] = {
            "status": "ready",
            "audio_url": fallback_tts_url,
            "ai_text": TTS_FALLBACK_TEXT,
            "error": type(e).__name__,
        }
        voice_info(
            "gpt_response_fallback_tts",
            call_sid=call_sid,
            client_id_prefix=str(call_data.get("client_id") or "")[:12],
        )
    finally:
        _persist_call_session(call_sid, call_data)


def should_forward_to_human(
    user_input: str,
    ai_response: str,
    *,
    call_sid: str = "",
    client_id: str = "",
) -> bool:
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
        "supervisor",
    ]

    # Check user input
    for keyword in forward_keywords:
        if keyword in user_lower:
            voice_forward(
                "caller_requested_human",
                call_sid=call_sid,
                client_id=client_id,
                forward_kind="fallback",
                matched_keyword=keyword,
                input_len=len(user_input or ""),
            )
            return True

    # Check AI response for forwarding signals (AI might detect intent)
    if "transfer" in ai_lower and ("you" in ai_lower or "connect" in ai_lower):
        voice_forward(
            "ai_transfer_intent_in_reply",
            call_sid=call_sid,
            client_id=client_id,
            forward_kind="fallback",
            reply_preview=(ai_response or "")[:80],
        )
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
    tts_url = (
        f"{base_url}/api/phone/tts-audio?text={message_encoded}&voice={get_tts_voice()}"
    )
    response.play(tts_url)

    clean_phone = "".join(c for c in forwarding_phone if c.isdigit() or c == "+")
    if not clean_phone.startswith("+"):
        if len(clean_phone) == 10:
            clean_phone = f"+1{clean_phone}"
        elif len(clean_phone) == 11 and clean_phone.startswith("1"):
            clean_phone = f"+{clean_phone}"
        else:
            clean_phone = f"+1{clean_phone}"

    voice_trace("dial_fallback_appended", dial_to=mask_phone(clean_phone))
    response.dial(clean_phone, timeout=30, record=False)
    response.say(
        "I'm sorry, no one is available right now. Please try again later or leave a message.",
        voice="alice",
    )
    response.hangup()


def forward_call_to_business(
    forwarding_phone: str, base_url: str, detected_lang: str = "English"
) -> VoiceResponse:
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
        if "client" not in globals() or client is None:
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
            temperature=0,  # Low temperature for consistent language detection
        )
        detected_lang = detection_response.choices[0].message.content.strip()

        # Clean up response (remove quotes, extra words, periods)
        detected_lang = (
            detected_lang.replace('"', "").replace("'", "").replace(".", "").strip()
        )

        # Extract just the language name (in case GPT adds extra text)
        # Take the first word which should be the language name
        detected_lang = (
            detected_lang.split()[0] if detected_lang.split() else detected_lang
        )

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
    prompt = build_system_prompt(
        business_info=info,
        detected_language=detected_language,
        caller_memory=caller_memory,
        include_booked_slots=include_booked_slots,
        booked_slots_prompt_text=booked_text,
    )
    from business_hours import after_hours_prompt_block

    after_hours = after_hours_prompt_block(info)
    if after_hours:
        prompt = f"{prompt}\n\n{after_hours}"
    return prompt






def _normalize_admin_phone(value: str) -> str:
    e164 = _phone_to_e164(value or "")
    return e164 or (value or "").strip()





@app.get("/api/me/access")
async def me_access(request: Request):
    """
    Debug helper for dashboard access issues: shows which Clerk user is signed in,
    which emails Clerk has on file, and whether a tenant membership exists in the DB.
    """
    token = get_bearer_token(request)
    if not token:
        return {"signed_in": False}
    try:
        user_id, jwt_tid = verify_clerk_token(token)
    except HTTPException:
        return {"signed_in": False, "token_invalid": True}
    _ensure_db_ready()
    tenant = db_tenant_get_for_user(user_id) if runtime.USE_DB else None
    link = _clerk_fetch_user_link(user_id) if runtime.USE_DB else None
    memberships = db_tenant_memberships_for_user(user_id) if runtime.USE_DB else []
    admin_ids = [
        x.strip()
        for x in (os.getenv("ADMIN_CLERK_USER_IDS") or "").split(",")
        if x.strip()
    ]
    primary_email = ((link or {}).get("emails") or [None])[0]
    pending_invite_tid = (
        db_tenant_invite_peek(primary_email) if runtime.USE_DB and primary_email else None
    )
    diagnosis = _membership_diagnosis(user_id, jwt_tid, link, tenant, memberships)
    return {
        "signed_in": True,
        "user_id": user_id,
        "is_admin": user_id in admin_ids,
        "jwt_metadata_tenant_id": jwt_tid,
        "clerk_api_tenant_id": (link or {}).get("tenant_id"),
        "clerk_emails": (link or {}).get("emails") or [],
        "db_tenant_client_id": (tenant or {}).get("client_id"),
        "db_tenant_id": (tenant or {}).get("id"),
        "db_tenant_name": (tenant or {}).get("name"),
        "has_tenant_membership": tenant is not None,
        "db_memberships": memberships,
        "pending_invite_for_primary_email": pending_invite_tid,
        "diagnosis": diagnosis,
    }


@app.get("/api/debug/cors")
async def debug_cors():
    """No-auth endpoint to verify CORS config on deployed backend. e.g. curl https://your-api/api/debug/cors"""
    return {"allowed_origins": allowed_origins}


@app.post("/api/conversation", response_model=ConversationResponse)
async def handle_conversation(
    request: ConversationRequest, _: None = Depends(require_active_subscription)
):
    try:
        # Always include booked slots so the AI knows which times are taken and avoids double-booking
        system_content = get_system_prompt(include_booked_slots=True)
        messages = [{"role": "system", "content": system_content}]
        if request.conversation_history:
            messages.extend(request.conversation_history)
        messages.append({"role": "user", "content": request.message})

        response = client.chat.completions.create(
            model="gpt-3.5-turbo", messages=messages, temperature=0.7, max_tokens=200
        )

        ai_response = response.choices[0].message.content
        action = None
        data = None

        # BOOKING: create appointment from AI output if present
        booking = parse_booking(ai_response)
        if booking:
            booking, repairs, reject = _prepare_parsed_booking(booking)
            if reject:
                system_info(
                    "chat_booking_line_rejected",
                    reason=reject,
                    repairs=repairs or None,
                )
                booking = None
            elif repairs:
                system_info("chat_booking_line_repaired", repairs=repairs)
        if booking:
            ok_booking, fail_msg, _, canonical_service = _validate_booking_requirements(
                booking
            )
            if not ok_booking:
                apt = None
            else:
                if canonical_service:
                    booking["reason"] = canonical_service
                apt = _create_appointment_from_booking(booking)
            if apt:
                ai_response = f"You're all set! We have you down for {apt['date']} at {_hhmm_to_ampm(apt.get('time', '') or '')}. The store will confirm shortly."
                action = "schedule_appointment"
                data = {"appointment_id": apt["id"]}
            else:
                ctx = booking_context_from_business(get_business_info())
                name_ok = bool((booking.get("name") or "").strip())
                date_ok = is_valid_booking_date(booking.get("date"))
                time_ok = looks_like_booking_time(booking.get("time"), ctx)
                if not ok_booking:
                    ai_response = (
                        fail_msg
                        or "Before I can book this, please choose a stylist and service."
                    )
                elif not name_ok:
                    ai_response = "I'd love to book that for you—what's your name?"
                elif not date_ok or not time_ok:
                    ai_response = "I need the date and time again to confirm—which day and time would you like?"
                else:
                    ai_response = "That time slot just got booked. Would you like to try another time or another day?"

        ai_response = _strip_booking_directive_for_voice(ai_response or "")
        if (
            "schedule" in request.message.lower()
            or "appointment" in request.message.lower()
        ):
            action = action or "schedule_appointment"
        elif (
            "message" in request.message.lower()
            or "leave a message" in request.message.lower()
        ):
            action = "take_message"
        elif (
            "transfer" in request.message.lower()
            or "department" in request.message.lower()
        ):
            action = "route_call"

        return ConversationResponse(response=ai_response, action=action, data=data)

    except Exception as e:
        raise _server_error("conversation endpoint failed", e)


def _send_appointment_email_notification(apt: dict, *, kind: str) -> bool:
    """Send submitted/confirmed email when enabled and provider is configured."""
    if not _appointment_email_enabled():
        return False
    from email_notify import format_appointment_email, send_appointment_email

    email = (apt.get("email") or "").strip()
    if not email:
        return False
    business_name = (get_business_info().get("name") or "us").strip()
    subject, html, text = format_appointment_email(
        kind=kind,
        business_name=business_name,
        customer_name=(apt.get("name") or "").strip(),
        date=apt.get("date") or "",
        time_ampm=_hhmm_to_ampm(apt.get("time") or ""),
        service=(apt.get("reason") or "").strip(),
    )
    ok = send_appointment_email(
        to=email, subject=subject, html_body=html, text_body=text
    )
    from observability import email_hint_for_log

    system_info(
        "appointment_email_notification",
        apt_id=apt.get("id"),
        kind=kind,
        sent=ok,
        email_hint=email_hint_for_log(email),
    )
    return ok


@app.post("/api/messages")
async def create_message(
    message: MessageRequest, _: None = Depends(require_active_subscription)
):
    try:
        data = {
            "caller_name": message.caller_name,
            "caller_phone": message.caller_phone,
            "message": message.message,
            "urgency": message.urgency,
            "status": "unread",
        }
        if runtime.USE_DB:
            message_data = db_messages_insert(data)
        else:
            message_data = {
                "id": len(messages) + 1,
                **data,
                "created_at": datetime.now().isoformat(),
            }
            messages.append(message_data)
        return {"success": True, "message": message_data}
    except Exception as e:
        raise _server_error("create message failed", e)




@app.get("/api/messages")
async def get_messages(_: None = Depends(require_active_subscription)):
    lst = db_messages_get_all() if runtime.USE_DB else messages
    return {"messages": lst}


@app.get("/api/business-info")
async def api_get_business_info(
    tenant: Optional[dict] = Depends(require_active_subscription),
):
    out = business_info_for_dashboard(tenant)
    if tenant:
        out["client_id"] = (tenant.get("client_id") or "").strip()
    _settings_load_debug_log_business_info(tenant, out)
    return out


@app.get("/api/greeting-preview")
async def api_greeting_preview(
    tenant: Optional[dict] = Depends(require_active_subscription),
):
    """
    Return the exact phone greeting text (placeholders resolved, recording line last).
    Use in Settings to verify what callers will hear before placing a test call.
    """
    tid = tenant or {}
    cid = (tid.get("client_id") or "").strip()
    if cid:
        set_request_client_id(cid)
    info = business_info_for_dashboard(tid) if tid else get_business_info()
    payload = build_phone_greeting_payload(info, tid or _tenant_for_call_recording())
    return payload


# Required and recommended fields so the AI receptionist can relay accurate info (any business type)
# Setup checklist labels must stay in sync with Settings.tsx checklist rows.
SETUP_REQUIRED_FIELDS = [
    ("name", "Business name"),
    ("hours", "Hours of operation"),
    ("forwarding_phone", "Store phone (real person)"),
    ("address", "Address"),
]


def get_setup_status(
    info_override: Optional[dict] = None, *, twilio_phone: Optional[str] = None
) -> dict:
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
        warnings.append(
            "Add services or departments so the AI knows what your business offers (e.g. appointments, estimates, emergency service)"
        )
    roster_ready = staff_roster_ready_for_booking(info)
    store_phone_ready = forwarding_phone_ready(info)
    voice_ready = roster_ready and store_phone_ready
    roster_only_gap = setup_transfers_to_store_after_message(info)
    if not roster_ready:
        if roster_only_gap:
            warnings.append(
                "Add at least one team member with a name on the Team roster so your AI receptionist can take calls. "
                "Until then, callers hear a message and are transferred to your store phone."
            )
        else:
            warnings.append(
                "Add at least one team member with a name on the Team roster so callers can book appointments."
            )
    if not store_phone_ready:
        warnings.append(
            "Add your store phone number so callers can be redirected to a real person when needed."
        )
    if not voice_ready and not roster_only_gap:
        warnings.append(
            "Your AI receptionist cannot take calls until setup is complete in Settings "
            "(team roster and store phone when both are needed)."
        )
    staff_count = len(
        [s for s in (info.get("staff") or []) if (s.get("name") or "").strip()]
    )
    service_count = len(_normalize_service_entries(info.get("services") or []))
    if roster_ready and staff_count >= 2 and service_count == 0:
        warnings.append(
            "Add services in Settings so callers can choose a service type during booking. "
            "Without a service menu, the AI will not ask which service they want."
        )
    twilio_number_set = bool((twilio_phone or "").strip())
    webhooks_configured = False
    if twilio_number_set:
        from twilio_provision import verify_webhooks_match_cached

        base = _public_base_url()
        if base and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
            verify = verify_webhooks_match_cached(
                account_sid=TWILIO_ACCOUNT_SID,
                auth_token=TWILIO_AUTH_TOKEN,
                phone=twilio_phone or "",
                base_url=base,
            )
            webhooks_configured = bool(verify.get("webhooks_configured"))
            if not webhooks_configured:
                warnings.append(
                    "Twilio webhooks for your AI phone number are missing or misconfigured. "
                    "Ask your admin to save the number again in Admin or set Voice + Messaging URLs in Twilio Console."
                )
        else:
            warnings.append(
                "AI phone number is set but webhook verification is unavailable (PUBLIC_BASE_URL or Twilio credentials missing on server)."
            )
    elif voice_ready:
        warnings.append(
            "No AI phone number is linked to this account yet. Your admin must assign a Twilio number before callers can reach the AI."
        )
    return {
        "complete": len(missing) == 0,
        "missing": missing,
        "warnings": warnings,
        "roster_ready": roster_ready,
        "forwarding_phone_ready": store_phone_ready,
        "voice_ready": voice_ready,
        "roster_only_gap": roster_only_gap,
        "twilio_number_set": twilio_number_set,
        "webhooks_configured": webhooks_configured,
        "onboarding_completed_at": (info.get("onboarding_completed_at") or "").strip()
        or None,
    }


@app.get("/api/setup-status")
async def api_setup_status(
    tenant: Optional[dict] = Depends(require_active_subscription),
):
    """Return which required/recommended business info fields are missing. Used for setup checklist."""
    info = business_info_for_dashboard(tenant)
    twilio_phone = (tenant or {}).get("twilio_phone_number") if tenant else None
    body = get_setup_status(info_override=info, twilio_phone=twilio_phone)
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


@app.post("/api/onboarding/complete")
async def api_onboarding_complete(
    tenant: Optional[dict] = Depends(require_active_subscription),
):
    """Mark guided onboarding as completed for this tenant."""
    if not tenant:
        raise HTTPException(status_code=403, detail="Tenant required")
    cid = (tenant.get("client_id") or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="client_id missing")
    set_request_client_id(cid)
    raw = _read_raw_client_config(cid) or _default_client_config_data(
        cid, tenant.get("plan") or "free"
    )
    raw["onboarding_completed_at"] = datetime.now(timezone.utc).isoformat()
    if runtime.USE_DB:
        if not db_tenant_set_business_config(cid, raw):
            raise HTTPException(
                status_code=500, detail="Failed to save onboarding state"
            )
    save_raw_client_config(cid, raw)
    info = business_info_for_dashboard(tenant)
    twilio_phone = tenant.get("twilio_phone_number")
    return get_setup_status(info_override=info, twilio_phone=twilio_phone)


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
    service_ids: List[str] = Field(default_factory=list)

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

    @field_validator("phone")
    @classmethod
    def validate_phone_optional(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            return ""
        digits = "".join(c for c in s if c.isdigit())
        if len(digits) < 10:
            raise ValueError("Phone must be at least 10 digits when provided.")
        return s

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

    @field_validator("service_ids", mode="before")
    @classmethod
    def normalize_service_ids(cls, v):
        if not v:
            return []
        if not isinstance(v, list):
            return []
        out: List[str] = []
        for item in v:
            raw = str(item).strip()
            if not raw:
                continue
            try:
                out.append(str(uuid.UUID(raw)))
            except ValueError:
                continue
        return out[:50]


def _valid_service_id_set(services_raw: Any) -> set[str]:
    return {
        s["id"] for s in _normalize_service_entries(services_raw or []) if s.get("id")
    }


def finalize_staff_records_for_storage(
    members: List[StaffMember],
    *,
    valid_service_ids: Optional[set[str]] = None,
) -> List[dict]:
    """Serialize staff for config.json; assign UUID when id omitted (backward compatible rows)."""
    out: List[dict] = []
    for m in members:
        sid = (m.id or "").strip() or str(uuid.uuid4())
        svc_ids: List[str] = []
        for raw_id in m.service_ids or []:
            rid = str(raw_id).strip()
            if not rid:
                continue
            if valid_service_ids is not None and rid not in valid_service_ids:
                continue
            svc_ids.append(rid)
        row: dict = {
            "id": sid,
            "name": m.name,
            "phone": m.phone,
            "email": m.email,
            "notes": m.notes,
        }
        if svc_ids:
            row["service_ids"] = svc_ids
        out.append(row)
    return out


from staff_transfers import (
    TransferTarget,
)  # noqa: E402 — after StaffMember; shared with PATCH validation


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
    transfer_targets: Optional[List[TransferTarget]] = None


@app.patch("/api/business-info")
async def api_update_business_info(
    update: BusinessInfoUpdate,
    request: Request,
    tenant: Optional[dict] = Depends(require_active_subscription),
):
    """Update business config (store info, voice, etc.). Writes to clients/<client_id>/config.json."""
    tid = tenant or {}
    cid = ((tid.get("client_id") or "").strip() or get_db_client_id()).strip()
    if not cid or cid == "default":
        raise HTTPException(status_code=400, detail="No client context")
    data = _read_raw_client_config(cid)
    if data is None:
        plan = tid.get("plan") or "free"
        if runtime.USE_DB:
            trow = db_tenant_get_by_client_id(cid)
            if trow and trow.get("plan"):
                plan = trow.get("plan") or plan
        data = _default_client_config_data(cid, plan)
    before_data = json.loads(json.dumps(data))
    voice_affecting = False
    if update.name is not None:
        data["business_name"] = update.name
        voice_affecting = True
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
        valid_svc = _valid_service_id_set(data["services"])
        if data.get("staff"):
            data["staff"] = [
                {
                    **s,
                    "service_ids": [
                        x for x in (s.get("service_ids") or []) if x in valid_svc
                    ],
                }
                for s in data["staff"]
            ]
    if update.specials is not None:
        data["specials"] = _normalize_special_entries(update.specials)
    if update.reservation_rules is not None:
        data["reservation_rules"] = _normalize_rule_entries(update.reservation_rules)
    if update.menu_link is not None:
        data["menu_link"] = update.menu_link
    if update.greeting is not None:
        data["greeting"] = update.greeting
        voice_affecting = True
    if update.voice is not None:
        data["voice"] = update.voice
        voice_affecting = True
    if update.speed is not None:
        data["speed"] = update.speed
        voice_affecting = True
    if update.receptionist_name is not None:
        data["receptionist_name"] = update.receptionist_name
        voice_affecting = True
    if update.business_type is not None:
        if not (runtime.USE_DB and tid and tid.get("business_vertical")):
            data["business_type"] = update.business_type
    if update.staff is not None:
        from staff_transfers import (
            STAFF_ROSTER_MAX,
            prune_transfer_targets_for_removed_staff,
        )

        new_staff = finalize_staff_records_for_storage(
            update.staff,
            valid_service_ids=_valid_service_id_set(data.get("services")),
        )
        if len(new_staff) > STAFF_ROSTER_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"Staff roster cannot exceed {STAFF_ROSTER_MAX} members. Contact support if you need more.",
            )
        old_ids = {str(s.get("id")) for s in (data.get("staff") or []) if s.get("id")}
        new_ids = {s["id"] for s in new_staff}
        removed_ids = old_ids - new_ids
        data["staff"] = new_staff
        if removed_ids and data.get("transfer_targets"):
            data["transfer_targets"] = prune_transfer_targets_for_removed_staff(
                list(data["transfer_targets"]), removed_ids
            )
    if update.transfer_targets is not None:
        from staff_transfers import (
            TransferTarget,
            finalize_transfer_targets_for_storage,
        )

        tenant_limits = db_tenant_get_by_client_id(cid) or tid
        transfer_max = 1
        if tenant_limits and get_plan_limits:
            transfer_max = int(get_plan_limits(tenant_limits).get("transfer_max") or 1)
        try:
            data["transfer_targets"] = finalize_transfer_targets_for_storage(
                update.transfer_targets,
                data.get("staff") or [],
                transfer_max=transfer_max,
            )
        except ValueError as e:
            msg = str(e)
            if msg.startswith("Plan allows"):
                raise HTTPException(status_code=403, detail=msg) from e
            raise HTTPException(status_code=400, detail=msg) from e
    save_raw_client_config(cid, data)
    if voice_affecting:
        invalidate_voice_cache(cid)
        create_tracked_task(
            _warm_client_voice_cache_async(cid), name=f"warm_voice_cache:{cid}"
        )
    if _greeting_debug_enabled():
        voice_info(
            "greeting_settings_saved",
            client_id_prefix=cid[:12],
            config_source="database" if runtime.USE_DB else "file",
            fields=[k for k in update.model_dump(exclude_none=True)],
            greeting_len=len(data.get("greeting") or ""),
            voice=data.get("voice"),
            receptionist_set=bool((data.get("receptionist_name") or "").strip()),
            business_name_len=len(data.get("business_name") or data.get("name") or ""),
        )
    changed_fields = [k for k in update.model_dump(exclude_none=True)]
    before_subset = {k: before_data.get(k) for k in changed_fields}
    after_subset = {k: data.get(k) for k in changed_fields}
    audit_log(
        "user",
        "business_info_updated",
        resource_type="config",
        client_id=cid,
        details={
            "fields": changed_fields,
            "before_sha256": _stable_sha256(
                json.dumps(before_subset, sort_keys=True, default=str)
            ),
            "after_sha256": _stable_sha256(
                json.dumps(after_subset, sort_keys=True, default=str)
            ),
        },
        request=request,
    )
    resp_tenant: dict = {**tid, "client_id": cid}
    if "plan" not in resp_tenant or not resp_tenant.get("plan"):
        resp_tenant["plan"] = data.get("plan") or "free"
    resp_tenant.setdefault("twilio_phone_number", tid.get("twilio_phone_number") or "")
    return business_info_for_dashboard(resp_tenant)


@app.get("/api/analytics/calls/{call_sid}/recording")
async def get_call_recording_audio(
    call_sid: str,
    tenant: Optional[dict] = Depends(require_tenant),
    _: None = Depends(require_active_subscription),
):
    """Stream call recording (MP3) from Twilio using server-side credentials; tenant must own the call."""
    if not tenant or not runtime.USE_DB:
        raise HTTPException(status_code=404, detail="Recording not available")
    if not _call_recording_enabled_for_tenant(tenant):
        raise HTTPException(status_code=404, detail="Recording not available")
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise HTTPException(
            status_code=503, detail="Recording playback is not configured"
        )
    row = db_call_log_get_by_call_sid(tenant["client_id"], call_sid)
    if not row or not row.get("recording_url"):
        raise HTTPException(status_code=404, detail="Recording not available")
    code, data = await asyncio.to_thread(
        _fetch_twilio_recording_bytes, row["recording_url"]
    )
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
async def text_to_speech(
    request: TTSRequest, _: None = Depends(require_active_subscription)
):
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
            speed=tts_speed,
        )

        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)

        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"},
        )

    except Exception as e:
        raise _server_error("text-to-speech failed", e)


# Phone call runtime state — runtime.call_store now lives in runtime (shared singleton). These
# alias its session/status dicts (same objects, only mutated) for main's phone routes.
active_calls = runtime.call_store.sessions
response_status = runtime.call_store.response_status

_background_tasks: set[asyncio.Task] = set()


def create_tracked_task(coro: Any, *, name: str) -> asyncio.Task:
    """Create background task with standardized failure logging and lifecycle cleanup."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        try:
            _ = t.result()
        except asyncio.CancelledError:
            logger.info("background_task_cancelled name=%s", name)
        except Exception:
            logger.exception("background_task_failed name=%s", name)

    task.add_done_callback(_done)
    return task


def cleanup_call_runtime_state(call_sid: str) -> None:
    """Clear per-call runtime state deterministically."""
    if not call_sid:
        return
    runtime.call_store.cleanup_call(call_sid)


# Fallback when OpenAI/TTS fails - play this so caller does not get dead air
TTS_FALLBACK_TEXT = (
    "We're experiencing a brief technical issue. Please try again in a moment."
)


@app.get("/api/phone/greeting-audio")
async def get_greeting_audio(request: Request):
    """Serve greeting audio using the voice selected in Settings. Cached on disk + in memory."""
    from voice.tts_cache import get_cached, put_cached

    client_id = _get_client_id_from_call(request)
    if not client_id:
        raise HTTPException(status_code=404, detail="Call session not found")
    set_request_client_id(client_id)
    call_sid = request.query_params.get("call_sid") or ""
    cache_key = _greeting_audio_cache_key(client_id)
    cached = get_cached(PROJECT_ROOT, "greeting", cache_key)
    info = get_business_info()
    tenant = _tenant_for_call_recording()
    preview_payload = build_phone_greeting_payload(info, tenant)
    if cached:
        _log_greeting_debug(
            "greeting_audio_cache_hit",
            preview_payload,
            call_sid=call_sid,
            cache_hit=True,
        )
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=greeting.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(cached)),
            },
        )
    try:
        voice = get_tts_voice()
        _log_greeting_debug(
            "greeting_audio_generating",
            preview_payload,
            call_sid=call_sid,
            cache_hit=False,
        )
        data = _synthesize_tts_clip(
            preview_payload["spoken_text"], voice=voice, speed=get_tts_speed()
        )
        put_cached(PROJECT_ROOT, "greeting", cache_key, data)
        voice_info(
            "greeting_audio_generated",
            client_id_prefix=(client_id or "")[:12],
            voice=voice,
            bytes=len(data),
            call_sid=call_sid or "",
        )
        return Response(
            content=data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=greeting.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(data)),
            },
        )
    except Exception as e:
        print(f"❌ Failed to generate greeting audio: {e}")
        import traceback

        traceback.print_exc()
        try:
            data = _synthesize_tts_clip(TTS_FALLBACK_TEXT, voice="fable", speed=1.0)
            put_cached(PROJECT_ROOT, "greeting", cache_key, data)
            return Response(
                content=data,
                media_type="audio/mpeg",
                headers={"Content-Length": str(len(data))},
            )
        except Exception as e2:
            print(f"❌ Fallback greeting audio failed: {e2}")
            raise HTTPException(
                status_code=500, detail=f"Failed to generate greeting: {e}"
            )


@app.get("/api/phone/got-it-audio")
async def get_got_it_audio(request: Request):
    """Serve 'Got it, one moment' using the receptionist voice. Cached on disk + in memory."""
    from voice.tts_cache import get_cached, put_cached

    client_id = _get_client_id_from_call(request)
    if not client_id:
        raise HTTPException(status_code=404, detail="Call session not found")
    set_request_client_id(client_id)
    cache_key = _got_it_cache_key(client_id)
    cached = get_cached(PROJECT_ROOT, "got_it", cache_key)
    if cached:
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=got-it.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(cached)),
            },
        )
    try:
        voice = cache_key[2]
        speed = cache_key[3]
        data = _synthesize_tts_clip(GOT_IT_PHRASE, voice=voice, speed=speed)
        put_cached(PROJECT_ROOT, "got_it", cache_key, data)
        voice_info(
            "got_it_audio_generated",
            client_id_prefix=(client_id or "")[:12],
            voice=voice,
            bytes=len(data),
        )
        return Response(
            content=data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=got-it.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(data)),
            },
        )
    except Exception as e:
        print(f"❌ Failed to generate 'got it' audio: {e}")
        import traceback

        traceback.print_exc()
        try:
            data = _synthesize_tts_clip(TTS_FALLBACK_TEXT, voice="fable", speed=1.0)
            put_cached(PROJECT_ROOT, "got_it", cache_key, data)
            return Response(
                content=data,
                media_type="audio/mpeg",
                headers={"Content-Length": str(len(data))},
            )
        except Exception as e2:
            print(f"❌ Fallback 'got it' audio failed: {e2}")
            raise HTTPException(
                status_code=500, detail=f"Failed to generate 'got it' audio: {e}"
            )


@app.get("/api/phone/one-moment-audio")
async def get_one_moment_audio(request: Request):
    """Serve 'One moment.' from cache for pending-response filler polling."""
    from voice.tts_cache import get_cached, put_cached

    client_id = _get_client_id_from_call(request)
    if not client_id:
        raise HTTPException(status_code=404, detail="Call session not found")
    set_request_client_id(client_id)
    cache_key = _one_moment_cache_key(client_id)
    cached = get_cached(PROJECT_ROOT, "one_moment", cache_key)
    if cached:
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=one-moment.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(cached)),
            },
        )
    try:
        voice = cache_key[2]
        speed = cache_key[3]
        data = _synthesize_tts_clip(ONE_MOMENT_PHRASE, voice=voice, speed=speed)
        put_cached(PROJECT_ROOT, "one_moment", cache_key, data)
        voice_info(
            "one_moment_audio_generated",
            client_id_prefix=(client_id or "")[:12],
            voice=voice,
            bytes=len(data),
        )
        return Response(
            content=data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=one-moment.mp3",
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(data)),
            },
        )
    except Exception as e:
        logger.exception("one_moment_audio_generate_failed: %s", e)
        try:
            data = _synthesize_tts_clip(TTS_FALLBACK_TEXT, voice="fable", speed=1.0)
            put_cached(PROJECT_ROOT, "one_moment", cache_key, data)
            return Response(
                content=data,
                media_type="audio/mpeg",
                headers={"Content-Length": str(len(data))},
            )
        except Exception as e2:
            logger.exception("one_moment_audio_fallback_failed: %s", e2)
            raise HTTPException(
                status_code=500, detail=f"Failed to generate 'one moment' audio: {e}"
            )


@app.post("/api/phone/incoming")
async def handle_incoming_call(request: Request):
    if not TWILIO_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Twilio not installed. Install with: pip install twilio",
        )
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

        # Multi-tenant: resolve tenant strictly by Twilio destination number.
        tenant = db_tenant_get_by_phone(to_number or "") if runtime.USE_DB else None
        tenant_for_access = tenant
        if tenant:
            set_request_client_id(tenant["client_id"])
            if (tenant.get("twilio_phone_number") or "").strip() == (
                to_number or ""
            ).strip():
                voice_info(
                    "tenant_resolved_by_to_number",
                    client_id=tenant["client_id"],
                    tenant_name=tenant.get("name") or "",
                    to_number=to_number,
                )
        else:
            voice_info("tenant_not_resolved", to_number=to_number)
        from webhook_responses import (
            check_webhook_tenant_access,
            subscription_denied_voice_twiml,
        )

        if not check_webhook_tenant_access(
            tenant_for_access,
            channel="voice",
            request_id=getattr(request.state, "request_id", None),
        ):
            return Response(
                content=subscription_denied_voice_twiml(),
                media_type="application/xml",
            )

        # Pre-call usage check: allow overage, log for billing (Option B)
        if runtime.USE_DB and tenant and get_plan_limits:
            limits = get_plan_limits(tenant)
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            usage = db_usage_get(tenant["client_id"], month)
            total = (usage.get("voice_minutes") or 0) + (usage.get("sms_count") or 0)
            if total >= limits.get("minutes_cap", 999999):
                audit_log(
                    "usage",
                    "overage_exceeded",
                    client_id=tenant["client_id"],
                    details={
                        "month": month,
                        "total": total,
                        "cap": limits.get("minutes_cap"),
                    },
                    request=request,
                )

        # Pro: call log start + customer memory for repeat callers
        call_log_start(call_sid, from_number, to_number)
        client_id = (tenant or {}).get("client_id") or ""
        if not client_id:
            if runtime.USE_DB:
                raise HTTPException(
                    status_code=403, detail="Unknown destination number"
                )
            client_id = CLIENT_ID or "default"
        caller_memory = refresh_caller_memory_for_prompt(from_number, client_id)

        # Create a new session for this call (store client_id for downstream handlers)
        session_id = f"phone-{call_sid}"
        set_request_client_id(client_id)
        greeting_plan = build_phone_greeting_payload(
            get_business_info(), tenant_for_access
        )
        _log_greeting_debug(
            "incoming_call_greeting_plan", greeting_plan, call_sid=call_sid or ""
        )
        voice_info(
            "incoming_call_greeting",
            call_sid=call_sid or "",
            client_id=client_id,
            config_source=greeting_plan.get("config_source"),
            spoken_preview=(greeting_plan.get("spoken_text") or "")[:500],
            voice=greeting_plan.get("voice"),
        )
        voice_info(
            "call_session_started",
            call_sid=call_sid,
            client_id=client_id,
            from_number=from_number,
            to_number=to_number,
        )

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

        active_calls[call_sid] = {
            "session_id": session_id,
            "from_number": from_number,
            "to_number": to_number,
            "client_id": client_id,
            "conversation_history": [],
            "detected_language": "English",
            "started_at": datetime.now().isoformat(),
            "caller_memory": caller_memory,
            "twilio_public_base_url": base_url,
        }
        biz_info = get_business_info()
        if staff_roster_ready_for_booking(biz_info):
            svc_n = len(_normalize_service_entries(biz_info.get("services") or []))
            staff_n = len(
                [
                    s
                    for s in (biz_info.get("staff") or [])
                    if (s.get("name") or "").strip()
                ]
            )
            if staff_n >= 2 and svc_n == 0:
                voice_info(
                    "booking_config_incomplete",
                    call_sid=call_sid or "",
                    client_id=client_id,
                    reason="no_services_multi_staff",
                    staff_count=staff_n,
                )
        if not voice_receptionist_ready(biz_info):
            voice_forward(
                "setup_not_ready_forward",
                call_sid=call_sid or "",
                client_id=client_id,
                forward_kind=(
                    "store_forwarding"
                    if setup_transfers_to_store_after_message(biz_info)
                    else "none"
                ),
                roster_ready=staff_roster_ready_for_booking(biz_info),
                store_phone_ready=forwarding_phone_ready(biz_info),
                roster_only_gap=setup_transfers_to_store_after_message(biz_info),
            )
            setup_twiml = twiml_setup_not_ready_handoff(
                base_url, biz_info, call_sid=call_sid or ""
            )
            return Response(content=str(setup_twiml), media_type="application/xml")

        if client_id:
            try:
                await asyncio.to_thread(_ensure_greeting_audio_cached, client_id)
            except Exception as e:
                voice_warning(
                    "greeting_cache_ensure_failed",
                    call_sid=call_sid or "",
                    client_id_prefix=client_id[:12],
                    error_type=type(e).__name__,
                )
                logger.warning(
                    "ensure greeting cache failed call_sid=%s client_id=%s: %s",
                    call_sid,
                    client_id,
                    e,
                    exc_info=True,
                )
            create_tracked_task(
                _warm_auxiliary_voice_cache_async(client_id),
                name=f"warm_voice_cache_aux:{client_id}",
            )

        # Create TwiML response
        response = VoiceResponse()

        if (
            TWILIO_AVAILABLE
            and VoiceResponse
            and _call_recording_enabled_for_tenant(tenant_for_access)
        ):
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
                voice_info(
                    "deepgram_requested_but_disabled", reason=env_r, call_sid=call_sid
                )
            else:
                voice_info(
                    "deepgram_requested_but_disabled",
                    reason="twilio_client_unavailable_or_twilio_not_installed",
                    call_sid=call_sid,
                )

        voice_call_phase(
            "incoming_greeting",
            call_sid=call_sid or "",
            client_id=client_id,
            stt="deepgram" if use_deepgram_stt else "twilio",
        )

        if use_deepgram_stt:
            from voice.twiml_stt import (
                append_connect_stream,
                append_deepgram_silence_followup_after_stream,
                next_media_stream_generation,
            )

            response.play(greeting_audio_url)
            gen = next_media_stream_generation(call_sid, active_calls[call_sid])
            append_connect_stream(
                response,
                call_sid=call_sid,
                base_url=base_url,
                stream_generation=gen,
            )
            still_there_url = (
                f"{base_url}/api/phone/tts-audio?text={quote('Still there?')}"
                f"&voice={get_tts_voice()}"
            )
            append_deepgram_silence_followup_after_stream(
                response,
                call_sid=call_sid,
                base_url=base_url,
                still_there_play_url=still_there_url,
                call_state=active_calls[call_sid],
            )
            _persist_call_session(call_sid)
            voice_debug(
                "incoming_deepgram_twiml_ready",
                call_sid=call_sid,
                media_stream_gen=runtime.call_store.get_media_stream_max_gen(call_sid),
                has_public_base_url=bool(
                    (runtime.call_store.get(call_sid) or {}).get("twilio_public_base_url")
                ),
            )
            return Response(content=str(response), media_type="application/xml")

        from voice.twiml_stt import append_gather_listen

        append_gather_listen(
            response,
            base_url,
            language="en-US",
            nested_play_url=greeting_audio_url,
        )

        return Response(content=str(response), media_type="application/xml")

    except HTTPException:
        # Intentional HTTP responses (e.g. 403 invalid-signature) must propagate —
        # the catch-all below would otherwise swallow them into a 200 fallback TwiML,
        # defeating the webhook signature gate.
        raise
    except Exception as e:
        voice_warning(
            "incoming_call_failed",
            error_type=type(e).__name__,
        )
        logger.exception("incoming_call_failed")
        response = VoiceResponse()
        base_url = _twilio_base_url(request)

        # On error, forward to business phone if available
        forwarding_phone = get_business_info().get("forwarding_phone")
        if forwarding_phone:
            voice_forward(
                "incoming_error_forward",
                call_sid=str(form_data.get("CallSid") if "form_data" in dir() else ""),
                forward_kind="fallback",
                has_fallback_configured=True,
                error_type=type(e).__name__,
            )
            error_text = "I'm experiencing technical difficulties. Let me connect you with someone who can help."
            error_encoded = quote(error_text)
            tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice={get_tts_voice()}"
            response.play(tts_audio_url)
            response = forward_call_to_business(forwarding_phone, base_url, "English")
            return Response(content=str(response), media_type="application/xml")
        else:
            # Fallback: just say error message if no forwarding number
            error_text = (
                "I'm sorry, I'm having technical difficulties. Please try again later."
            )
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
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
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
        if not client_id and runtime.USE_DB:
            client_id = db_call_log_get_client_id_by_call_sid(call_sid)
        if not client_id:
            voice_warning(
                "recording_complete_unresolved_call_sid", call_sid=call_sid or ""
            )
            return Response(content="", status_code=200, media_type="text/plain")
        set_request_client_id(client_id)

        tenant_rec = (
            db_tenant_get_by_client_id(client_id) if runtime.USE_DB and client_id else None
        )
        if not _call_recording_enabled_for_tenant(tenant_rec):
            voice_info(
                "recording_complete_ignored_plan",
                call_sid=call_sid or "",
                client_id_prefix=(client_id or "")[:12],
            )
            return Response(content="OK", status_code=200, media_type="text/plain")

        if runtime.USE_DB:
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
        if not runtime.USE_DB:
            _file_call_log_merge_recording(
                call_sid,
                recording_sid=recording_sid,
                recording_url=recording_url,
                recording_duration_sec=duration_sec,
                recording_status=recording_status,
            )

        st = (recording_status or "").lower()
        if (
            st == "completed"
            and recording_url
            and _call_summary_enabled_for_tenant(tenant_rec)
        ):
            create_tracked_task(
                _schedule_recording_summary(
                    call_sid, client_id, recording_url, duration_sec
                ),
                name=f"recording_summary:{call_sid}",
            )
        return Response(content="", status_code=200, media_type="text/plain")
    except Exception as e:
        logger.exception("recording-complete webhook error: %s", e)
        return Response(content="", status_code=200, media_type="text/plain")


@app.post("/api/phone/process-speech")
async def process_speech(request: Request):
    if not TWILIO_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Twilio not installed. Install with: pip install twilio",
        )
    """
    Process speech input from phone call and generate AI response.
    """
    try:
        form_data = await request.form()
        if not _validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = form_data.get("CallSid")
        speech_result = form_data.get("SpeechResult", "")
        confidence = form_data.get("Confidence", "0")

        voice_info(
            "speech_received",
            call_sid=call_sid or "",
            transcript_len=len(speech_result or ""),
            confidence=confidence,
        )

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
            return Response(
                content=outcome.replacement_twiml, media_type="application/xml"
            )

        response = VoiceResponse()
        got_it_audio_url = f"{base_url}/api/phone/got-it-audio?call_sid={call_sid}"
        response.play(got_it_audio_url)
        response.redirect(
            f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
        )

        return Response(content=str(response), media_type="application/xml")

    except Exception as e:
        voice_warning(
            "process_speech_failed",
            call_sid=str(call_sid if "call_sid" in dir() else ""),
            error_type=type(e).__name__,
        )
        logger.exception("process_speech_failed")

        # On error, offer to forward to a real person
        response = VoiceResponse()
        base_url = _twilio_base_url(request)

        # Check if we have a forwarding number - if so, forward on error
        forwarding_phone = get_business_info().get("forwarding_phone")
        if forwarding_phone:
            voice_forward(
                "process_speech_error_forward",
                call_sid=str(call_sid if "call_sid" in dir() else ""),
                forward_kind="fallback",
                has_fallback_configured=True,
                error_type=type(e).__name__,
            )
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
        if not _validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")

        voice_call_phase(
            "call_status",
            call_sid=call_sid or "",
            status=call_status or "",
        )
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
            if not client_id_before and runtime.USE_DB and call_sid in call_log_entries:
                client_id_before = call_log_entries[call_sid].get("client_id")
            if not from_number_before and call_sid in call_log_entries:
                from_number_before = call_log_entries[call_sid].get("from_number")
            duration_sec = 0
            if call_sid in call_log_entries:
                duration_sec = call_log_entries[call_sid].get("duration_sec") or 0
            if call_sid in active_calls:
                call_data = active_calls[call_sid]
                outcome = call_data.get("outcome")
                if not outcome and appointment_created:
                    outcome = "answered_by_ai"
                    call_data["outcome"] = outcome
                elif (
                    not outcome
                    and call_data.get("booking_intent")
                    and not appointment_created
                ):
                    outcome = "no_booking"
                    call_data["outcome"] = outcome
                if outcome:
                    call_log_set_outcome(call_sid, outcome)
                from_number = call_data.get("from_number")
                if from_number:
                    update_caller_memory(from_number)
                call_log_end(call_sid)
                cleanup_call_runtime_state(call_sid or "")
                voice_call_phase(
                    "call_session_cleaned",
                    call_sid=call_sid or "",
                    client_id=str(client_id_before or ""),
                    outcome=outcome or "",
                    duration_sec=duration_sec,
                )
            elif call_sid in call_log_entries:
                # Call was logged but not in active_calls (e.g. quick hangup)
                call_log_set_outcome(
                    call_sid, "missed" if call_status == "completed" else call_status
                )
                call_log_end(call_sid)
                cleanup_call_runtime_state(call_sid or "")
            # Lead capture: when call ended without booking and plan allows
            if (
                runtime.USE_DB
                and client_id_before
                and client_id_before != "default"
                and from_number_before
                and get_plan_limits
            ):
                try:
                    tenant = db_tenant_get_by_client_id(client_id_before)
                    if (
                        tenant
                        and get_plan_limits(tenant).get("has_lead_capture")
                        and not appointment_created
                    ):
                        db_leads_insert(
                            client_id_before,
                            None,
                            from_number_before,
                            "inquiry",
                            "call",
                        )
                except Exception as e:
                    logger.error(
                        "lead_capture_failed",
                        extra={"client_id": client_id_before, "error": str(e)},
                    )
            # Record voice usage for billing (graceful degradation: log on failure, do not raise)
            if runtime.USE_DB and client_id_before and client_id_before != "default":
                try:
                    minutes = max(0, math.ceil(duration_sec / 60))
                    month = datetime.now(timezone.utc).strftime("%Y-%m")
                    if not db_usage_increment_voice(client_id_before, month, minutes):
                        logger.error(
                            "usage_increment_failed",
                            extra={
                                "client_id": client_id_before,
                                "month": month,
                                "error": "db_usage_increment_voice returned False",
                            },
                        )
                except Exception as e:
                    logger.error(
                        "usage_increment_failed",
                        extra={"client_id": client_id_before, "error": str(e)},
                    )

        return Response(content="OK", media_type="text/plain")

    except Exception as e:
        voice_warning("call_status_handler_failed", error_type=type(e).__name__)
        logger.exception("call_status_handler_failed")
        return Response(content="OK", media_type="text/plain")


@app.websocket("/api/phone/media")
async def phone_media_websocket(websocket: WebSocket):
    """Twilio Media Streams → Deepgram Nova-2 live STT (when VOICE_STT_PROVIDER=deepgram)."""
    if not TWILIO_AVAILABLE or not runtime.twilio_client:
        await websocket.close(code=1011)
        return
    from voice.media_ws import handle_phone_media_websocket

    await handle_phone_media_websocket(websocket, runtime.twilio_client)


@app.post("/api/phone/stream")
async def handle_media_stream(request: Request):
    """
    Legacy placeholder. Real-time media uses WebSocket ``GET /api/phone/media`` (Twilio Media Streams).
    """
    return {
        "message": "Use WebSocket wss://…/api/phone/media for Twilio Media Streams (VOICE_STT_PROVIDER=deepgram).",
        "websocket_path": "/api/phone/media",
    }


@app.post("/api/phone/no-speech")
async def handle_no_speech(request: Request):
    """
    After listen windows expire with no caller speech: forward to fallback number only here,
    not on every AI turn. Caller must stay silent through Still there? + second listen.
    """
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed")
    try:
        form_data = await request.form()
        if not _validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = _call_sid_from_form(form_data)
        _restore_call_context(call_sid or "")
        base_url = _twilio_base_url(request)
        call_data = active_calls.get(call_sid, {}) if call_sid else {}
        detected_lang = call_data.get("detected_language") or "English"
        forwarding_phone = (get_business_info().get("forwarding_phone") or "").strip()

        # Race: caller spoke (Deepgram REST update) while TwiML still had a queued no-speech redirect.
        if call_sid and call_sid in response_status:
            st = (response_status.get(call_sid) or {}).get("status") or "pending"
            voice_respond_branch(
                "no_speech_skipped_active_turn",
                call_sid=call_sid,
                client_id=str(call_data.get("client_id") or ""),
                status=st,
            )
            response = VoiceResponse()
            response.redirect(
                f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
            )
            return Response(content=str(response), media_type="application/xml")

        # After AI spoke, silence on the follow-up listen is expected — re-prompt once, do not
        # bounce to /respond (response_status was cleared when the reply TwiML was returned).
        if call_data.get("awaiting_caller_reply"):
            from voice.twiml_stt import empty_retry_twiml

            runtime.call_store.merge_session(call_sid, {"awaiting_caller_reply": False})
            voice_respond_branch(
                "no_speech_post_ai_reprompt",
                call_sid=call_sid or "",
                client_id=str(call_data.get("client_id") or ""),
                status="reprompt",
            )
            lang_code = get_twilio_language_code(detected_lang)
            xml = empty_retry_twiml(
                base_url=base_url,
                language=lang_code,
                use_deepgram=_voice_stt_use_deepgram(),
                call_sid=call_sid,
                call_state=active_calls.get(call_sid, {}),
            )
            return Response(content=xml, media_type="application/xml")

        if forwarding_phone:
            voice_forward(
                "no_speech_timeout",
                call_sid=call_sid or "",
                client_id=str(call_data.get("client_id") or ""),
                forward_kind="fallback",
                has_fallback_configured=True,
            )
            if call_sid:
                _merge_call_session(call_sid, {"outcome": "forwarded"})
            if call_sid:
                call_log_set_outcome(call_sid, "forwarded")
            response = forward_call_to_business(
                forwarding_phone, base_url, detected_lang
            )
        else:
            voice_respond_branch(
                "no_speech_goodbye",
                call_sid=call_sid or "",
                client_id=str(call_data.get("client_id") or ""),
                status="hangup",
            )
            response = VoiceResponse()
            goodbye_text = "Thanks for calling! Have a wonderful day!"
            goodbye_url = f"{base_url}/api/phone/tts-audio?text={quote(goodbye_text)}&voice={get_tts_voice()}"
            response.play(goodbye_url)
            response.hangup()
        return Response(content=str(response), media_type="application/xml")
    except Exception as e:
        voice_warning(
            "no_speech_handler_failed",
            call_sid=(form_data.get("CallSid") if "form_data" in dir() else "") or "",
            error_type=type(e).__name__,
        )
        logger.exception("no_speech_handler_failed")
        response = VoiceResponse()
        response.say("Thanks for calling. Goodbye.", voice="alice")
        response.hangup()
        return Response(content=str(response), media_type="application/xml")


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
        if not _validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = _call_sid_from_form(form_data)
        _restore_call_context(call_sid or "")
        # base_url needed for forward_call_to_business in all branches
        base_url = _twilio_base_url(request)
        if not call_sid or call_sid not in response_status:
            # GPT still processing or caller has not spoken yet — keep polling; never auto-forward.
            call_data_poll = active_calls.get(call_sid, {}) if call_sid else {}
            voice_respond_branch(
                "poll_no_status",
                call_sid=call_sid or "",
                client_id=str(call_data_poll.get("client_id") or ""),
                status="pending",
                has_active_call=bool(call_sid and call_sid in active_calls),
            )
            response = VoiceResponse()
            filler_audio_url = (
                f"{base_url}/api/phone/one-moment-audio?call_sid={call_sid}"
            )
            response.play(filler_audio_url)
            response.pause(length=1)
            response.redirect(
                f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
            )
            return Response(content=str(response), media_type="application/xml")

        status_data = response_status[call_sid]
        status = status_data.get("status", "pending")
        response = VoiceResponse()

        if status == "ready":
            call_data = active_calls.get(call_sid, {})
            voice_respond_branch(
                "play_ai_reply",
                call_sid=call_sid or "",
                client_id=str(call_data.get("client_id") or ""),
                status="ready",
                stt_provider="deepgram" if _voice_stt_use_deepgram() else "twilio",
            )
            # Audio is ready - play it
            audio_url = status_data.get("audio_url")
            if audio_url:
                response.play(audio_url)
                try:
                    # After playing, set up next input gathering
                    detected_lang = call_data.get("detected_language") or "English"
                    twilio_lang_code = get_twilio_language_code(detected_lang)
                    still_there_url = f"{base_url}/api/phone/tts-audio?text={quote('Still there?')}&voice={get_tts_voice()}"

                    if uses_non_latin_script(
                        detected_lang
                    ) and not _conversation_prefers_english_stt(call_data):
                        response.record(
                            action=f"{base_url}/api/phone/process-recording",
                            method="POST",
                            max_length=15,
                            finish_on_key="#",
                            recording_status_callback=f"{base_url}/api/phone/recording-status",
                        )
                        response.say(
                            "Please speak now, then press pound when done.",
                            language="en-US",
                        )
                    else:
                        from voice.twiml_stt import (
                            append_post_ai_listen_with_still_there,
                        )

                        append_post_ai_listen_with_still_there(
                            response,
                            call_sid=call_sid,
                            base_url=base_url,
                            twilio_lang_code=twilio_lang_code,
                            still_there_play_url=still_there_url,
                            use_deepgram=_voice_stt_use_deepgram(),
                            call_state=active_calls.get(call_sid, {}),
                        )
                        if call_sid:
                            runtime.call_store.merge_session(
                                call_sid, {"awaiting_caller_reply": True}
                            )
                except Exception as e:
                    voice_warning(
                        "respond_ready_listen_setup_failed",
                        call_sid=call_sid or "",
                        client_id=str(call_data.get("client_id") or "")[:12],
                        error_type=type(e).__name__,
                        error_detail=str(e)[:200],
                    )
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
                voice_forward(
                    "respond_status_forward",
                    call_sid=call_sid or "",
                    client_id=str(
                        active_calls.get(call_sid, {}).get("client_id") or ""
                    ),
                    forward_kind="fallback_or_staff",
                    has_fallback_configured=True,
                )
                detected_lang = active_calls.get(call_sid, {}).get(
                    "detected_language"
                ) or "English"
                response = forward_call_to_business(
                    forwarding_phone, base_url, detected_lang
                )
                # Clean up status
                if call_sid in response_status:
                    del response_status[call_sid]
                return Response(content=str(response), media_type="application/xml")

        elif status == "error":
            # Error occurred - forward to business phone if available
            forwarding_phone = get_business_info().get("forwarding_phone")
            if forwarding_phone:
                voice_forward(
                    "respond_status_error_forward",
                    call_sid=call_sid or "",
                    client_id=str(
                        active_calls.get(call_sid, {}).get("client_id") or ""
                    ),
                    forward_kind="fallback",
                    has_fallback_configured=True,
                )
                detected_lang = active_calls.get(call_sid, {}).get(
                    "detected_language"
                ) or "English"
                response = forward_call_to_business(
                    forwarding_phone, base_url, detected_lang
                )
                # Clean up status
                if call_sid in response_status:
                    del response_status[call_sid]
                return Response(content=str(response), media_type="application/xml")
            else:
                voice_respond_branch(
                    "error_no_fallback",
                    call_sid=call_sid or "",
                    status="error",
                )
                # Fallback: return error message if no forwarding number
                response.say(
                    "I'm sorry, I'm having technical difficulties. Please try again later.",
                    voice="alice",
                )
                response.hangup()
                # Clean up status
                if call_sid in response_status:
                    del response_status[call_sid]
                return Response(content=str(response), media_type="application/xml")

        else:
            voice_respond_branch(
                "poll_pending",
                call_sid=call_sid or "",
                client_id=str(active_calls.get(call_sid, {}).get("client_id") or ""),
                status=status,
            )
            # Still pending - play filler and redirect again
            # Use OpenAI TTS (Fable voice) for consistency
            filler_text = "One sec."
            filler_encoded = quote(filler_text)
            filler_audio_url = f"{base_url}/api/phone/tts-audio?text={filler_encoded}&voice={get_tts_voice()}"
            response.play(filler_audio_url)
            response.pause(length=1)
            response.redirect(
                f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
            )
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
            voice_forward(
                "respond_endpoint_exception_forward",
                call_sid=str(call_sid or ""),
                client_id=str(
                    active_calls.get(call_sid or "", {}).get("client_id") or ""
                ),
                forward_kind="fallback",
                has_fallback_configured=True,
                error_type=type(e).__name__,
            )
            # Try to get call data for language
            call_data = active_calls.get(call_sid, {})
            detected_lang = call_data.get("detected_language") or "English"
            response = forward_call_to_business(
                forwarding_phone, base_url, detected_lang
            )
            # Clean up status
            if call_sid in response_status:
                del response_status[call_sid]
            return Response(content=str(response), media_type="application/xml")
        else:
            voice_respond_branch(
                "respond_endpoint_exception",
                call_sid=str(call_sid or ""),
                status="error",
                error_type=type(e).__name__,
            )
            # Fallback: return error message if no forwarding number
            response.say(
                "I'm sorry, I'm having technical difficulties. Please try again later.",
                voice="alice",
            )
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
            speed=get_tts_speed(),
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
                "Cache-Control": "no-cache",
            },
        )
    except Exception as e:
        raise _server_error("HD TTS generation failed", e)


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
            speed=get_tts_speed(),
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
                "Cache-Control": "no-cache",
            },
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
            raise _server_error("TTS fallback also failed", e2)


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
        if not _validate_twilio_webhook(request, dict(form_data)):
            return Response(
                content="Forbidden", status_code=403, media_type="text/plain"
            )
        call_sid = _call_sid_from_form(form_data)
        recording_url = form_data.get("RecordingUrl", "")
        _restore_call_context(call_sid or "")

        logger.info("recording_received call_sid=%s", call_sid or "")

        if not call_sid or call_sid not in active_calls:
            response = VoiceResponse()
            response.say(
                "I'm sorry, I lost track of our conversation. Please call back.",
                voice="alice",
            )
            return Response(content=str(response), media_type="application/xml")

        if not recording_url:
            logger.warning("recording_missing_url call_sid=%s", call_sid or "")
            response = VoiceResponse()
            response.say(
                "I didn't receive the recording. Please try again.", voice="alice"
            )
            bu = _twilio_base_url(request)
            if bu:
                response.redirect(f"{bu}/api/phone/process-speech", method="POST")
            return Response(content=str(response), media_type="application/xml")

        if not _is_trusted_twilio_media_url(recording_url):
            logger.warning("recording_url_untrusted_host call_sid=%s", call_sid or "")
            response = VoiceResponse()
            response.say(
                "I had trouble processing the recording. Please try again.",
                voice="alice",
            )
            bu = _twilio_base_url(request)
            if bu:
                response.redirect(f"{bu}/api/phone/process-speech", method="POST")
            return Response(content=str(response), media_type="application/xml")

        call_data = active_calls.get(call_sid, {})

        # Download the recording from Twilio using httpx
        # httpx is already available in the environment
        try:
            import httpx
        except ImportError:
            # Fallback if httpx not available (shouldn't happen)
            raise HTTPException(status_code=500, detail="httpx library not available")

        recording_response = httpx.get(
            recording_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=30.0
        )
        if recording_response.status_code != 200:
            logger.warning(
                "recording_download_failed call_sid=%s status=%s",
                call_sid or "",
                recording_response.status_code,
            )
            response = VoiceResponse()
            response.say(
                "I had trouble processing the recording. Please try again.",
                voice="alice",
            )
            bu = _twilio_base_url(request)
            if bu:
                response.redirect(f"{bu}/api/phone/process-speech", method="POST")
            return Response(content=str(response), media_type="application/xml")

        # Transcribe with Whisper
        audio_data = recording_response.content
        temp_file = io.BytesIO(audio_data)
        temp_file.name = "recording.wav"

        logger.info("recording_transcribe_start call_sid=%s", call_sid or "")
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=temp_file,
            # language parameter omitted to allow auto-detection
        )

        speech_result = transcript.text
        logger.info(
            "recording_transcribe_ok call_sid=%s transcript_len=%s",
            call_sid or "",
            len(speech_result or ""),
        )

        base_url = _twilio_base_url(request)
        rec_key = (form_data.get("RecordingSid") or recording_url or "").strip()
        if rec_key and call_data.get("_last_processed_recording") == rec_key:
            voice_info("process_recording_duplicate_skipped", call_sid=call_sid or "")
            response = VoiceResponse()
            response.redirect(
                f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
            )
            return Response(content=str(response), media_type="application/xml")
        if rec_key:
            rec_updates: dict[str, Any] = {"_last_processed_recording": rec_key}
            if _text_looks_latin(speech_result):
                rec_updates["detected_language"] = "English"
            _merge_call_session(call_sid, rec_updates)

        from voice.utterance import apply_caller_utterance

        outcome = await apply_caller_utterance(
            call_sid or "",
            speech_result or "",
            0.9,
            base_url,
        )
        if outcome.mode == "replace_call_twiml" and outcome.replacement_twiml:
            return Response(
                content=outcome.replacement_twiml, media_type="application/xml"
            )

        response = VoiceResponse()
        response.play(f"{base_url}/api/phone/got-it-audio?call_sid={call_sid}")
        response.redirect(
            f"{base_url}/api/phone/respond?CallSid={call_sid}", method="POST"
        )
        return Response(content=str(response), media_type="application/xml")

    except Exception as e:
        voice_warning(
            "process_recording_failed",
            call_sid=str(call_sid if "call_sid" in dir() else ""),
            error_type=type(e).__name__,
        )
        logger.exception("process_recording_failed")
        response = VoiceResponse()
        base_url = _twilio_base_url(request)

        # On error, forward to business phone if available
        forwarding_phone = get_business_info().get("forwarding_phone")
        if forwarding_phone:
            voice_forward(
                "process_recording_error_forward",
                call_sid=str(call_sid if "call_sid" in dir() else ""),
                forward_kind="fallback",
                has_fallback_configured=True,
                error_type=type(e).__name__,
            )
            # Try to get call data for language
            call_data = active_calls.get(call_sid, {})
            detected_lang = call_data.get("detected_language") or "English"
            response = forward_call_to_business(
                forwarding_phone, base_url, detected_lang
            )
            return Response(content=str(response), media_type="application/xml")
        else:
            # Fallback: ask to try again if no forwarding number
            response.say(
                "I'm sorry, I had trouble processing that. Please try again.",
                voice="alice",
            )
            response.redirect(f"{base_url}/api/phone/process-speech", method="POST")
            return Response(content=str(response), media_type="application/xml")


@app.post("/api/phone/recording-status")
async def recording_status(request: Request):
    """Handle recording status updates from Twilio"""
    # This endpoint can be used for logging or additional processing
    form_data = await request.form()
    if not _validate_twilio_webhook(request, dict(form_data)):
        return Response(content="Forbidden", status_code=403, media_type="text/plain")
    logger.info("recording_status_update status=%s", form_data.get("RecordingStatus"))
    return Response(content="OK", media_type="text/plain")


@app.post("/api/phone/transcribe")
async def transcribe_phone_audio(request: Request, audio_data: str = Form(...)):
    """
    Transcribe audio from phone call using OpenAI Whisper.
    This endpoint receives base64-encoded audio from Twilio.
    """
    try:
        if not _validate_twilio_webhook(request, {"audio_data": audio_data}):
            raise HTTPException(status_code=403, detail="Forbidden")
        # Decode base64 audio
        audio_bytes = base64.b64decode(audio_data)

        # Save to temporary file
        temp_file = io.BytesIO(audio_bytes)
        temp_file.name = "audio.webm"

        # Transcribe using OpenAI Whisper - auto-detect language for multi-language support
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=temp_file,
            # language parameter omitted to allow auto-detection of any language
        )

        return {"transcript": transcript.text}

    except Exception as e:
        raise _server_error("transcription failed", e)


@app.get("/api/phone/calls")
async def get_active_calls(_: str = Depends(require_admin)):
    """Admin-only: list in-flight voice sessions (PII — never public)."""
    return {
        "active_calls": len(active_calls),
        "calls": [
            {
                "call_sid": sid,
                "from": call_data["from_number"],
                "to": call_data["to_number"],
                "started_at": call_data["started_at"],
            }
            for sid, call_data in active_calls.items()
        ],
    }


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 50)
    print("Starting Call Surge Backend Server")
    print("=" * 50)
    print(f"Server will run on: http://0.0.0.0:8000")
    print(f"Local access: http://localhost:8000")
    print("=" * 50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
