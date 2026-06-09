"""Conversation service — the AI voice-receptionist booking logic.

The voice/SMS conversation brain lifted out of main: booking-intent detection, the
GPT booking-line extraction, BOOKING: parsing/validation, appointment creation from a
parsed booking, and system-prompt composition. The /api/conversation route stays in
main and calls these via re-export. Cross-module helpers are module-qualified
(config_service / booking_service / database / sms_service / runtime); pure leaf logic
(booking_fields / business_hours / prompts.receptionist / observability) is imported by name.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import booking_service
import config_service
import database
import runtime
import sms_service
from observability import system_info
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
from business_hours import (
    after_hours_prompt_block,
    is_past_closing_for_date,
    same_day_after_hours_message,
)
from prompts.receptionist import (
    build_system_prompt,
    caller_message_suggests_pricing,
    latest_user_message,
)

logger = logging.getLogger("nuvatra")

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


def _phones_match_for_booking(a: str, b: str) -> bool:
    da = sms_service.normalize_phone(a or "")
    db = sms_service.normalize_phone(b or "")
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
    cid = (client_id or "").strip() or database._client_id()
    if not cid:
        return 0
    want_staff = booking_service._staff_slot_key(staff_id)
    norm_time = booking_service._normalize_time_to_hhmm(time) or time
    cancelled = 0
    for apt in booking_service._appointment_rows_for_calendar_merge():
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
        apt_time = booking_service._normalize_time_to_hhmm(apt.get("time") or "") or (
            apt.get("time") or ""
        )
        if apt_time != norm_time:
            continue
        if booking_service._staff_slot_key(apt.get("staff_id")) != want_staff:
            continue
        if phone and not _phones_match_for_booking(phone, apt.get("phone") or ""):
            continue
        aid = apt.get("id")
        if not aid:
            continue
        try:
            database.db_appointments_update(int(aid), status="cancelled", client_id=cid)
            booking_service.release_slot(int(aid))
            cancelled += 1
        except Exception as e:
            logger.warning("supersede_voice_booking_draft failed apt_id=%s: %s", aid, e)
    if cancelled:
        booking_service._invalidate_booked_slots_cache()
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
    for s in (info or config_service.get_business_info()).get("staff") or []:
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
    biz = info or config_service.get_business_info()
    services = config_service._normalize_service_entries(biz.get("services") or [])
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
    biz = info or config_service.get_business_info()
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
    biz = info or config_service.get_business_info()
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

    services = config_service._normalize_service_entries(biz.get("services") or [])
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
    if not config_service.staff_roster_ready_for_booking(config_service.get_business_info()):
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
    biz = config_service.get_business_info()
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
        for s in config_service._normalize_service_entries(biz.get("services") or [])
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
        resp = runtime.client.chat.completions.create(
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
    biz = config_service.get_business_info()
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
    ctx = booking_context_from_business(info or config_service.get_business_info())
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
    staff = config_service.get_business_info().get("staff") or []
    for s in staff:
        sid = (s.get("id") or "").strip()
        if sid and frag == sid:
            return sid
        name = (s.get("name") or "").strip()
        if name and frag.lower() == name.lower():
            return sid if sid else None
    return None


def _staff_name_set(info: Optional[dict] = None) -> set[str]:
    biz = info or config_service.get_business_info()
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
    biz = info or config_service.get_business_info()
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
    biz = info or config_service.get_business_info()
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
    service_name, service_required = booking_service._normalize_service_choice_for_booking(
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
            for s in config_service._normalize_service_entries(biz.get("services") or [])[:5]
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
            for s in config_service._normalize_service_entries(biz.get("services") or [])[:5]
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
    ctx = booking_context_from_business(config_service.get_business_info())
    time = normalize_booking_time(time_raw) or ""
    if not is_valid_booking_date(date) or not looks_like_booking_time(time, ctx):
        return None
    _apply_booking_customer_name(booking, caller_memory=caller_memory)
    name = (booking.get("name") or "").strip()
    if not name or not date or not time:
        return None
    cid_for_slot = (client_id_override or "").strip() or database._client_id()
    if cid_for_slot:
        database.set_request_client_id(cid_for_slot)
    staff_key = resolve_staff_id_from_booking_fragment(booking.get("staff"))
    canonical_service, _ = booking_service._normalize_service_choice_for_booking(booking.get("reason"))
    if canonical_service:
        booking["reason"] = canonical_service
    duration_min = booking_service._booking_duration_minutes(booking)
    _supersede_pending_customer_drafts_for_slot(
        date,
        time,
        staff_key,
        client_id=cid_for_slot,
        phone=(booking.get("phone") or "").strip(),
    )
    if not booking_service.is_slot_available(date, time, duration_min, staff_key):
        booking_service._invalidate_booked_slots_cache()  # Next prompt build will see slot as taken
        blockers = booking_service._slot_blocking_details(
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
        row = database.db_appointments_insert(appointment_data)
        apt_id = row["id"]
    else:
        apt_id = len(runtime.appointments) + 1
        appointment_data["id"] = apt_id
        appointment_data["created_at"] = datetime.now().isoformat()
        runtime.appointments.append(appointment_data)
    if reserve_slot_immediately:
        booking_service.reserve_slot(date, time, apt_id, duration_min, staff_key)
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


def get_system_prompt(
    detected_language: str = "English",
    caller_memory: Optional[dict] = None,
    include_booked_slots: bool = False,
    skip_slots_cache: bool = False,
):
    """Compose GPT system prompt for voice; slot lines come from live booking state."""
    info = config_service.get_business_info()
    booked_text = None
    if include_booked_slots:
        booked_text = booking_service.get_booked_slots_prompt_text(skip_cache=skip_slots_cache)
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
