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


# Cross-cutting URL + background-task helpers now live in deps; re-export.
from deps import (  # noqa: E402,F401
    _public_base_url,
    _derived_public_base_from_request,
    _twilio_base_url,
    create_tracked_task,
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
from routers import phone as phone_router
from routers import business as business_router

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
app.include_router(phone_router.router)
app.include_router(business_router.router)

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
    cleanup_call_runtime_state,
    invalidate_voice_cache,
    TTS_FALLBACK_TEXT,
    # voice call flow: TwiML handoffs, forwarding, language detection (cut 7)
    setup_transfers_to_store_after_message,
    setup_not_ready_call_message,
    _normalize_dial_number,
    append_dial_forwarding_only,
    twiml_setup_not_ready_handoff,
    twiml_roster_not_ready_handoff,
    parse_transfer_to,
    get_twilio_language_code,
    should_forward_to_human,
    append_forward_call_verbs,
    forward_call_to_business,
    detect_language,
)

# AI voice-receptionist booking logic now lives in conversation_service; re-export so the
# /api/conversation route + phone/SMS handlers still in main (and tests patching these)
# keep resolving. Owning module = conversation_service.
from conversation_service import (  # noqa: E402,F401
    _phones_match_for_booking,
    _supersede_pending_customer_drafts_for_slot,
    _suggests_booking,
    _conversation_user_text,
    _caller_indicated_stylist_choice,
    _caller_indicated_service_choice,
    _staff_choice_required,
    _conversation_suggests_booking,
    _count_booking_user_turns,
    _voice_booking_nudge_message,
    _ai_implies_committed_booking,
    _should_attempt_voice_booking_extraction,
    _extract_booking_line_from_conversation,
    _prepare_parsed_booking,
    parse_booking,
    _strip_booking_directive_for_voice,
    resolve_staff_id_from_booking_fragment,
    _staff_name_set,
    _caller_memory_name_usable,
    _apply_booking_customer_name,
    _validate_booking_requirements,
    _create_appointment_from_booking,
    get_system_prompt,
    generate_response_async,
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
    # staff-roster / voice-readiness checks (business-config derived)
    get_staff_phone_by_name,
    staff_on_roster,
    staff_roster_ready_for_booking,
    forwarding_phone_ready,
    voice_receptionist_ready,
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








# _validate_twilio_webhook now lives in deps (cross-cutting webhook-auth helper used by
# the SMS/phone routers and main's remaining webhook routes); re-export so the ~9 callers
# still in main and tests patching it keep resolving.
from deps import _validate_twilio_webhook  # noqa: E402,F401




# Call log (Pro analytics): in-memory index by call_sid, persisted to JSON
# Booking-creation flow (voice/SMS-adjacent; the slot/calendar engine lives in booking_service).






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


# Required and recommended fields so the AI receptionist can relay accurate info (any business type)
# Setup checklist labels must stay in sync with Settings.tsx checklist rows.


from staff_transfers import (
    TransferTarget,
)  # noqa: E402 — after StaffMember; shared with PATCH validation


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


# Phone call runtime state — runtime.call_store now lives in runtime (shared singleton). These
# alias its session/status dicts (same objects, only mutated) for main's phone routes.
active_calls = runtime.call_store.sessions
response_status = runtime.call_store.response_status

# Fallback when OpenAI/TTS fails - play this so caller does not get dead air
if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 50)
    print("Starting Call Surge Backend Server")
    print("=" * 50)
    print(f"Server will run on: http://0.0.0.0:8000")
    print(f"Local access: http://localhost:8000")
    print("=" * 50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
