"""Business-config loading and normalization (shared service).

Resolves a tenant's business configuration from PostgreSQL (production) or the
on-disk clients/<id>/config.json (local dev), normalizes it to the shape the
voice/SMS code expects, and exposes get_business_info()/get_tts_* helpers.

Pulled out of main.py so routers can use it without importing main. DB calls are
module-qualified (database.X) so they stay patchable in tests.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException

import database
import runtime

logger = logging.getLogger("nuvatra")

# Repo root (parent of backend/) for on-disk client configs — same value main computes.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def _config_data_to_business_info(data: dict) -> dict:
    """Normalize raw config.json / DB business_config dict to get_business_info() shape."""
    forwarding = data.get("forwarding_phone") or ""
    if not forwarding and data.get("locations"):
        forwarding = data["locations"][0].get("forwarding_phone", "")
    _departments = data.get("departments")
    if not isinstance(_departments, list):
        _departments = []
    return {
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
        "transfer_targets": data.get("transfer_targets", []),
        "locations": data.get("locations", []),
        "greeting": data.get("greeting", ""),
        "plan": data.get("plan", "starter"),
        "voice": data.get("voice", "fable"),
        "speed": (
            float(data.get("speed", 1.0)) if data.get("speed") is not None else 1.0
        ),
        "receptionist_name": data.get("receptionist_name", ""),
        "business_type": data.get("business_type", ""),
        # How the tenant's AI line is reached: "new" = the provisioned Twilio number IS
        # their published number; "existing" = they keep their own number and forward
        # calls to the (hidden) Twilio line. existing_business_number is the number
        # customers actually dial in "existing" mode — display-only, used for forwarding
        # instructions in onboarding/Settings.
        "number_mode": data.get("number_mode") or "new",
        "existing_business_number": data.get("existing_business_number", ""),
    }


def client_config_source(cid: str) -> str:
    """Where business config was loaded from: database, file, or none."""
    c = (cid or "").strip()
    if not c:
        return "none"
    if runtime.USE_DB:
        try:
            if database.db_tenant_get_business_config(c):
                return "database"
        except Exception:
            pass
    config_path = PROJECT_ROOT / "clients" / c / "config.json"
    if config_path.exists():
        return "file"
    return "none"


def _read_raw_client_config(cid: str) -> Optional[dict]:
    """Load raw config from PostgreSQL (production) then clients/<cid>/config.json (local dev)."""
    raw = None
    if runtime.USE_DB:
        try:
            raw = database.db_tenant_get_business_config(cid)
        except Exception as e:
            logger.warning("business_config db read failed client_id=%s: %s", cid, e)
    if raw is not None:
        return raw
    config_path = PROJECT_ROOT / "clients" / cid / "config.json"
    if not config_path.exists():
        logger.debug("client_config_missing path=%s client_id=%s", config_path, cid)
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if runtime.USE_DB and raw:
            try:
                database.db_tenant_set_business_config(cid, raw)
            except Exception as e:
                logger.warning(
                    "business_config file->db migrate failed client_id=%s: %s", cid, e
                )
        return raw
    except Exception as e:
        logger.warning("Failed to read client config file client_id=%s: %s", cid, e)
        return None


def save_raw_client_config(cid: str, data: dict) -> None:
    """Persist business config to DB (required on Render) and optionally to clients/<cid>/config.json."""
    db_ok = True
    if runtime.USE_DB:
        db_ok = bool(database.db_tenant_set_business_config(cid, data))
        if not db_ok:
            raise HTTPException(
                status_code=500, detail="Failed to save settings to database"
            )
    config_path = PROJECT_ROOT / "clients" / cid / "config.json"
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        if not runtime.USE_DB:
            raise HTTPException(
                status_code=500, detail=f"Failed to write config: {e}"
            ) from e
        logger.warning(
            "config file write failed client_id=%s (saved to db): %s", cid, e
        )


def load_client_config(client_id: Optional[str] = None):
    """Load business config for client_id (DB first, then on-disk file)."""
    cid = (client_id or database._client_id()).strip()
    if not cid:
        return None
    raw = _read_raw_client_config(cid)
    if not raw:
        return None
    try:
        info = _config_data_to_business_info(raw)
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
    "transfer_targets": [],
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
        "name": (tenant.get("name") or "").strip(),
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
        "transfer_targets": [],
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
    if not runtime.USE_DB:
        return None
    cid = database._client_id()
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
            if not (out.get("name") or "").strip():
                out["name"] = (tenant.get("name") or "").strip()
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
    """Seed clients/<client_id>/config.json from template when present."""
    template_path = PROJECT_ROOT / "clients" / "template" / "config.json"
    if template_path.is_file():
        try:
            base = json.loads(template_path.read_text(encoding="utf-8"))
            if isinstance(base, dict):
                out = dict(base)
                out["client_id"] = client_id
                out["plan"] = plan
                # The template ships placeholder example staff (Manager/Reception) for
                # human reference; a freshly-created tenant must start with an empty
                # roster so the owner adds their own team, not inherit the placeholders.
                out["staff"] = []
                return out
        except Exception as e:
            logger.warning("template_config_load_failed err=%s", e)
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
        "transfer_targets": [],
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
        if not out.get("phone") and runtime.USE_DB:
            cid = database._client_id()
            if cid:
                tenant = database.db_tenant_get_by_client_id(cid)
                if tenant:
                    out["phone"] = tenant.get("twilio_phone_number") or ""
    else:
        tenant_info = _default_business_info_for_tenant()
        if tenant_info:
            out = dict(tenant_info)
        else:
            out = dict(_DEMO_BUSINESS_INFO)
    if runtime.USE_DB:
        cid = database._client_id()
        if cid:
            t = database.db_tenant_get_by_client_id(cid)
            if t:
                bv = (t.get("business_vertical") or "salon_chair").strip()
                out["business_vertical"] = bv
                out["business_vertical_label"] = BUSINESS_VERTICAL_LABELS.get(bv, bv)
                if not (out.get("name") or "").strip():
                    out["name"] = (t.get("name") or "").strip()
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


def get_client_data_dir() -> Optional[Path]:
    """Path to the client data directory (call_log, caller_memory on local/file mode).
    None when there's no real client_id."""
    cid = database._client_id()
    if not cid or cid == "default":
        return None
    d = PROJECT_ROOT / "clients" / cid
    d.mkdir(parents=True, exist_ok=True)
    return d


# ===== staff-roster / voice-readiness checks (business-config derived) =====


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
