"""
Call transfer targets (plan-limited) vs unlimited staff roster (booking / calendar).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator

_log = logging.getLogger("nuvatra")

# Practical ceiling to prevent config abuse; not a billing limit (see plans.PLAN_TRANSFER_MAX).
STAFF_ROSTER_MAX = 500


def _sanitize_single_line(raw: Optional[str], max_len: int) -> str:
    if raw is None:
        return ""
    s = "".join(c for c in str(raw) if ord(c) >= 32)
    return s.strip()[:max_len]


def normalize_transfer_phone(phone: str) -> Optional[str]:
    """E.164 for Twilio dial; None if invalid."""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) >= 10:
        return f"+{digits}"
    return None


class TransferTarget(BaseModel):
    id: Optional[str] = Field(default=None, max_length=36)
    staff_id: Optional[str] = Field(default=None, max_length=36)
    name: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=32)

    @field_validator("id", "staff_id", mode="before")
    @classmethod
    def strip_optional_uuid(cls, v):
        if v is None:
            return None
        vv = str(v).strip()
        return vv if vv else None

    @field_validator("id", "staff_id")
    @classmethod
    def uuid_when_set(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            return str(uuid.UUID(v))
        except ValueError as e:
            raise ValueError("Transfer target id must be a valid UUID.") from e

    @field_validator("name", mode="before")
    @classmethod
    def sanitize_name(cls, v):
        return _sanitize_single_line(v, 120)

    @field_validator("phone", mode="before")
    @classmethod
    def sanitize_phone(cls, v):
        return _sanitize_single_line(v, 32)


def finalize_transfer_targets_for_storage(
    targets: List[TransferTarget],
    staff_rows: List[dict],
    *,
    transfer_max: int,
) -> List[dict]:
    """
    Validate and serialize transfer targets. Raises ValueError with user-safe message.
    """
    cap = max(0, int(transfer_max))
    if len(targets) > cap:
        raise ValueError(f"Plan allows up to {cap} call transfer destination(s). Upgrade to add more.")

    staff_by_id = {str(s.get("id")): s for s in staff_rows if s.get("id")}
    seen_staff: set[str] = set()
    out: List[dict] = []

    for t in targets:
        sid = (t.staff_id or "").strip() or None
        if sid:
            if sid not in staff_by_id:
                raise ValueError("Transfer target references a staff member that is not on your roster.")
            if sid in seen_staff:
                raise ValueError("Each staff member can only appear once in call transfers.")
            seen_staff.add(sid)

        name = (t.name or "").strip()
        if sid and not name:
            name = str(staff_by_id[sid].get("name") or "").strip()
        if not name:
            raise ValueError("Each transfer destination needs a name callers can ask for.")

        phone_raw = (t.phone or "").strip()
        if sid:
            staff_phone = str(staff_by_id[sid].get("phone") or "").strip()
            if staff_phone:
                phone_raw = staff_phone
        if not phone_raw:
            raise ValueError(f"Transfer destination “{name}” needs a valid phone number.")
        e164 = normalize_transfer_phone(phone_raw)
        if not e164:
            raise ValueError(f"Transfer destination “{name}” has an invalid phone number.")

        tid = (t.id or "").strip() or str(uuid.uuid4())
        out.append({"id": tid, "staff_id": sid, "name": name, "phone": e164})

    return out


def resolve_transfer_destinations(business_info: dict) -> List[dict[str, str]]:
    """
    Resolved {name, phone} pairs authorized for live TRANSFER_TO dialing.
  Falls back to legacy staff-with-phone rows when transfer_targets is empty.
    """
    staff = business_info.get("staff") or []
    staff_by_id = {str(s.get("id")): s for s in staff if s.get("id")}
    targets = business_info.get("transfer_targets")

    if isinstance(targets, list) and targets:
        out: List[dict[str, str]] = []
        for t in targets:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name") or "").strip()
            sid = str(t.get("staff_id") or "").strip() or None
            phone_raw = str(t.get("phone") or "").strip()
            if sid and sid in staff_by_id:
                st = staff_by_id[sid]
                if not name:
                    name = str(st.get("name") or "").strip()
                sp = str(st.get("phone") or "").strip()
                if sp:
                    phone_raw = sp
            if not name or not phone_raw:
                continue
            e164 = normalize_transfer_phone(phone_raw)
            if e164:
                out.append({"name": name, "phone": e164})
        return out

    # Legacy: staff list phones (pre–transfer_targets migration)
    legacy: List[dict[str, str]] = []
    for s in staff:
        name = str(s.get("name") or "").strip()
        phone_raw = str(s.get("phone") or "").strip()
        if not name or not phone_raw:
            continue
        e164 = normalize_transfer_phone(phone_raw)
        if e164:
            legacy.append({"name": name, "phone": e164})
    return legacy


def staff_members_for_pending_review_sms(staff_list: List[dict], apt: dict) -> List[dict]:
    """
    Staff to notify when a booking needs shop approval.
    If the appointment has staff_id, only that roster member (when they have a phone).
    Otherwise all roster members with a phone (legacy broadcast).
    """
    assigned = str(apt.get("staff_id") or "").strip()
    if assigned:
        for s in staff_list:
            if not isinstance(s, dict):
                continue
            if str(s.get("id") or "").strip() == assigned:
                return [s] if (s.get("phone") or "").strip() else []
        return []
    return [s for s in staff_list if isinstance(s, dict) and (s.get("phone") or "").strip()]


def get_transfer_phone_by_name(name: str, business_info: Optional[dict] = None) -> Optional[str]:
    """Match transfer destination by name (case-insensitive). First match wins."""
    info = business_info or {}
    name_clean = (name or "").strip().lower()
    if not name_clean:
        return None
    for dest in resolve_transfer_destinations(info):
        if dest.get("name", "").strip().lower() == name_clean:
            return dest.get("phone")
    return None


def transfer_names_for_prompt(business_info: dict) -> List[str]:
    return [d["name"] for d in resolve_transfer_destinations(business_info) if d.get("name")]


def prune_transfer_targets_for_removed_staff(
    targets: List[dict], removed_staff_ids: set[str]
) -> List[dict]:
    if not removed_staff_ids:
        return targets
    return [t for t in targets if str(t.get("staff_id") or "") not in removed_staff_ids]
