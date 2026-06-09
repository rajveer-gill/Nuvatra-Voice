"""Caller memory — repeat-caller recognition (name/history) shared by the voice and
SMS receptionist flows. DB-backed when USE_DB, else a per-client JSON file.

Lifted out of main.py so the SMS and voice routers can both reach it without importing
main. Helpers are module-qualified (database / config_service / sms_service / runtime).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import config_service
import database
import runtime
import sms_service
from observability import system_info

logger = logging.getLogger("nuvatra")


def get_caller_memory(phone: str) -> Optional[dict]:
    """Load caller memory for repeat-caller recognition. Returns None or {name, call_count, last_call_iso, last_reason}."""
    if runtime.USE_DB:
        return database.db_caller_memory_get(phone)
    data_dir = config_service.get_client_data_dir()
    if not data_dir:
        return None
    path = data_dir / "caller_memory.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        key = sms_service.normalize_phone(phone)
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


def refresh_caller_memory_for_prompt(
    phone: str, client_id: Optional[str] = None
) -> Optional[dict]:
    """
    Load caller memory for voice/SMS prompts, syncing name/email from the latest appointment
    when the DB row is stale (e.g. still 'Jake' after the customer texted a new name).
    """
    mem = get_caller_memory(phone)
    if not runtime.USE_DB:
        return mem
    cid = (client_id or "").strip() or database._client_id()
    if not cid:
        return mem
    try:
        database.set_request_client_id(cid)
        identity = database.db_appointments_latest_identity_for_phone(phone, client_id=cid)
    except Exception as e:
        logger.warning("refresh_caller_memory_for_prompt failed: %s", e)
        return mem
    if not identity:
        return mem
    apt_name = (identity.get("name") or "").strip()
    apt_email = (identity.get("email") or "").strip()
    mem_name = ((mem or {}).get("name") or "").strip()
    mem_email = ((mem or {}).get("email_on_file") or "").strip()
    needs_sync = bool(apt_name and apt_name.lower() != mem_name.lower()) or bool(
        apt_email and apt_email.lower() != mem_email.lower()
    )
    if not needs_sync:
        return mem
    dp: dict = {}
    if apt_email:
        dp["email_on_file"] = apt_email
    try:
        update_caller_memory(
            phone,
            name=apt_name or None,
            increment_count=False,
            data_patch=dp if dp else None,
        )
        system_info(
            "caller_memory_synced_from_appointment",
            client_id=cid,
            had_prior_name=bool(mem_name),
        )
    except Exception as e:
        logger.warning("caller_memory_sync_from_appointment failed: %s", e)
        return mem
    return get_caller_memory(phone)


def update_caller_memory(
    phone: str,
    name: Optional[str] = None,
    last_reason: Optional[str] = None,
    increment_count: bool = True,
    data_patch: Optional[dict] = None,
):
    """Update caller memory after a call (increment count, set last call time and optional reason)."""
    if runtime.USE_DB:
        database.db_caller_memory_upsert(
            phone,
            name=name,
            last_reason=last_reason,
            increment_count=increment_count,
            data_patch=data_patch,
        )
        return
    data_dir = config_service.get_client_data_dir()
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
    key = sms_service.normalize_phone(phone)
    entry = data.setdefault(
        key,
        {
            "name": "",
            "call_count": 0,
            "last_call_iso": "",
            "last_reason": "",
            "data": {},
        },
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
