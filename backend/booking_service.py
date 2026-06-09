"""Booking service: stateless appointment primitives.

Duration/time-formatting/service-canonicalization/staff-name/validation helpers
lifted out of main.py (strangler-fig refactor). Pure functions — no runtime or DB
state; depend only on config_service + stdlib. The stateful slot-storage/calendar
engine (load/save/cache/reserve/release/merge/reconcile) is a separate follow-up.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

from fastapi import HTTPException

import config_service

DEFAULT_SLOT_DURATION_MINUTES = 30

def _service_duration_minutes_for_reason(
    reason: Optional[str], info: Optional[dict] = None
) -> Optional[int]:
    """Return configured service duration when reason matches the menu; else None."""
    raw = (reason or "").strip()
    if not raw or raw == "—":
        return None
    biz = info or config_service.get_business_info()
    canonical, _ = _normalize_service_choice_for_booking(raw, biz)
    search = (canonical or raw).strip().lower()
    if not search:
        return None
    for svc in config_service._normalize_service_entries(biz.get("services") or []):
        nm = (svc.get("name") or "").strip().lower()
        if not nm:
            continue
        if search == nm or search in nm or nm in search:
            try:
                return max(
                    5,
                    min(
                        int(svc.get("duration_minutes") or DEFAULT_SLOT_DURATION_MINUTES),
                        480,
                    ),
                )
            except (TypeError, ValueError):
                return DEFAULT_SLOT_DURATION_MINUTES
    return None

def _booking_duration_minutes(
    booking: dict, info: Optional[dict] = None
) -> int:
    dm = _service_duration_minutes_for_reason(booking.get("reason"), info)
    return dm if dm is not None else DEFAULT_SLOT_DURATION_MINUTES

def _appointment_duration_minutes(
    apt: dict, info: Optional[dict] = None
) -> int:
    dm = _service_duration_minutes_for_reason(apt.get("reason"), info)
    return dm if dm is not None else DEFAULT_SLOT_DURATION_MINUTES

def _duration_minutes_for_appointment(
    apt: dict,
    slots_by_appointment_id: dict[int, int],
    services: Optional[List[dict]] = None,
) -> int:
    """Resolve block length for calendar display (service menu, then booked_slots, else default)."""
    info = {"services": services} if services is not None else None
    svc_dm = _service_duration_minutes_for_reason(apt.get("reason"), info)
    if svc_dm is not None:
        return svc_dm
    try:
        aid = int(apt.get("id") or 0)
    except (TypeError, ValueError):
        aid = 0
    if aid and aid in slots_by_appointment_id:
        return max(5, min(int(slots_by_appointment_id[aid]), 480))
    return DEFAULT_SLOT_DURATION_MINUTES

def _time_to_minutes(t: str) -> int:
    """Parse time string (e.g. '10', '10:00', '2:00 PM') to minutes since midnight."""
    if not t:
        return 0
    raw = (t or "").strip()
    upper = raw.upper()
    meridian: Optional[str] = None
    if re.search(r"\bP\.?\s*M\.?\b", upper) or re.search(r"\bPM\b", upper):
        meridian = "pm"
    elif re.search(r"\bA\.?\s*M\.?\b", upper) or re.search(r"\bAM\b", upper):
        meridian = "am"
    cleaned = re.sub(r"(?i)\s*(a\.?\s*m\.?|p\.?\s*m\.?)\s*$", "", raw).strip()
    cleaned = re.sub(r"(?i)\s*(am|pm)\s*$", "", cleaned).strip()
    parts = cleaned.split(":")
    h = 0
    m = 0
    try:
        if parts:
            h = int("".join(c for c in parts[0] if c.isdigit()) or "0")
        if len(parts) > 1:
            m = int("".join(c for c in parts[1] if c.isdigit()) or "0")
    except (ValueError, TypeError):
        pass
    if meridian == "pm":
        if h != 12:
            h += 12
    elif meridian == "am":
        if h == 12:
            h = 0
    elif meridian is None and cleaned:
        # Salon-style times without AM/PM: 9–11 → AM, 1–8 → PM, 12 → noon
        if h == 12:
            pass
        elif 1 <= h <= 8:
            h += 12
    return h * 60 + m

def _normalize_time_to_hhmm(t: str) -> str:
    """Normalize time to HH:MM (e.g. '10' -> '10:00', '10:00 AM' -> '10:00')."""
    if not t or not (t or "").strip():
        return ""
    mins = _time_to_minutes(t)
    h, m = divmod(mins, 60)
    return f"{h:02d}:{m:02d}"

def _format_appointment_details_confirmation_sms(apt: dict) -> str:
    """Full appointment summary for SMS — used after voice booking and when customer updates details."""
    phone_display = (apt.get("phone") or "").strip() or "Not provided"
    time_display = _hhmm_to_ampm(apt.get("time") or "") or (apt.get("time") or "")
    service = (apt.get("reason") or "").strip() or "—"
    status = (apt.get("status") or "").strip()
    customer = (apt.get("name") or "").strip()
    stylist = _staff_display_name_for_appointment(apt)
    if customer:
        customer_line = f"Customer: {customer}"
    else:
        customer_line = (
            "Customer: Not on file yet — reply with your name if we should update it."
        )
    stylist_line = f"Stylist: {stylist}\n" if stylist else ""
    if status == "pending_customer":
        intro = "Here's what we have for you — the time is NOT locked in until you text back YES or CONFIRM:"
        footer = (
            "Reply YES or CONFIRM only when this looks exactly right — that reserves the time and sends this to the store. "
            "You can also reply with changes.\n\n"
        )
    else:
        intro = "Here's your updated appointment info on file:"
        footer = "Reply if anything still needs to change.\n\n"
    return (
        f"Hey! {intro}\n"
        f"{customer_line}\n"
        f"{stylist_line}"
        f"Phone: {phone_display}\n"
        f"Date: {apt.get('date', '')}\n"
        f"Time: {time_display}\n"
        f"Service: {service}\n\n"
        f"{footer}"
        f"Msg & data rates may apply. Reply STOP to opt out."
    )

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

def _staff_display_name_for_appointment(apt: dict, info: Optional[dict] = None) -> str:
    sid = (apt.get("staff_id") or "").strip()
    if not sid:
        return ""
    for s in (info or config_service.get_business_info()).get("staff") or []:
        if (s.get("id") or "").strip() == sid:
            return (s.get("name") or "").strip()
    return ""

def _normalize_service_choice_for_booking(
    reason_raw: Optional[str], info: Optional[dict] = None
) -> tuple[Optional[str], bool]:
    """Return (canonical_service_name_or_none, service_required)."""
    biz = info or config_service.get_business_info()
    services = config_service._normalize_service_entries((biz or {}).get("services") or [])
    if not services:
        return (reason_raw or "").strip() or None, False
    reason = (reason_raw or "").strip()
    if not reason or reason == "—":
        return None, True
    reason_l = reason.lower()
    for s in services:
        nm = (s.get("name") or "").strip()
        if not nm:
            continue
        nml = nm.lower()
        if reason_l == nml or reason_l in nml or nml in reason_l:
            return nm, True
    return None, True

def _optional_staff_id_validated(raw: Optional[str]) -> Optional[str]:
    """If staff_id is set, ensure it matches a row in this tenant's staff list."""
    sid = (raw or "").strip()
    if not sid:
        return None
    for s in config_service.get_business_info().get("staff") or []:
        if (s.get("id") or "").strip() == sid:
            return sid
    raise HTTPException(status_code=400, detail="Invalid staff_id for this business.")

def _appointment_email_enabled() -> bool:
    """Off by default; set APPOINTMENT_EMAIL_ENABLED=1 to send Resend/SMTP confirmations."""
    return (os.getenv("APPOINTMENT_EMAIL_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
