"""Conversation service — the AI voice-receptionist booking logic.

The voice/SMS conversation brain lifted out of main: booking-intent detection, the
GPT booking-line extraction, BOOKING: parsing/validation, appointment creation from a
parsed booking, and system-prompt composition. The /api/conversation route stays in
main and calls these via re-export. Cross-module helpers are module-qualified
(config_service / booking_service / database / sms_service / runtime); pure leaf logic
(booking_fields / business_hours / prompts.receptionist / observability) is imported by name.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from typing import List, Optional

import booking_service
import caller_memory
import config_service
import database
import runtime
import sms_service
import voice_service
from observability import (
    name_initial_for_log,
    sms_info,
    system_info,
    voice_call_phase,
    voice_debug,
    voice_forward,
    voice_info,
    voice_transcript,
    voice_warning,
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
from business_hours import (
    after_hours_prompt_block,
    business_local_now,
    is_past_closing_for_date,
    same_day_after_hours_message,
)
from prompts.receptionist import (
    build_system_prompt,
    caller_message_suggests_pricing,
    latest_user_message,
)

logger = logging.getLogger("nuvatra")

# Voice reasoning model. gpt-4o-mini is faster and cheaper than gpt-3.5-turbo and far more
# reliable at per-stylist scheduling (gpt-3.5 would misapply one stylist's working days to
# another). Override via VOICE_LLM_MODEL to roll back or A/B a different model without a deploy.
VOICE_LLM_MODEL = (os.getenv("VOICE_LLM_MODEL") or "gpt-4o-mini").strip()

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
    Cancel stale voice bookings so the same caller can rebook / modify without leaving duplicates.
    - pending_customer: unconfirmed draft (slot not held until SMS YES). When the caller's phone is
      known, ALL of their same-date drafts are superseded — so a mid-call change to the time,
      service, or stylist replaces the draft instead of leaving a stale one. Without a phone, falls
      back to exact-slot matching.
    - pending_review: same caller + receptionist source at the exact slot — frees a held slot when
      they call again.
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
        if (apt.get("date") or "") != date:
            continue
        if st == "pending_customer" and phone:
            # An unconfirmed draft holds no slot, so a caller should have at most one per day.
            # Match any of THIS caller's same-date drafts so a mid-call change (time, service, OR
            # stylist) REPLACES the draft instead of leaving a stale duplicate on the dashboard.
            if not _phones_match_for_booking(phone, apt.get("phone") or ""):
                continue
        else:
            # pending_review (a held slot) or an anonymous draft with no caller phone: only
            # supersede the exact same slot, and for pending_review require the same caller +
            # receptionist source so we never free an unrelated held slot.
            if st == "pending_review":
                if (apt.get("source") or "").strip() != "receptionist":
                    continue
                if not phone or not _phones_match_for_booking(
                    phone, apt.get("phone") or ""
                ):
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

    services = config_service._normalize_service_entries(biz.get("services") or [])
    ctx = booking_context_from_business(biz)

    # Service-first: when a service menu exists, get the service before the stylist.
    if services and not service_choice_resolved(conversation_history, ctx):
        if turns >= 2 and not assistant_asked_service_recently(conversation_history):
            return (
                f"BOOKING REMINDER: This caller wants an appointment ({turns} user turns). "
                "Ask ONE short question: which service from the menu they'd like. Do NOT ask which "
                "stylist yet—after they choose a service, suggest only the stylists who provide it."
            )
        return None

    # Service chosen (or no menu) → now resolve the stylist if required.
    if _staff_choice_required(biz) and not _caller_indicated_stylist_choice(user_text, biz):
        if turns >= 2:
            return (
                f"BOOKING REMINDER: Caller picked a service ({turns} turns) but no stylist yet. "
                "Ask ONE short question: which stylist they prefer (or anyone is fine), suggesting "
                "only those who provide the chosen service."
            )
        return None

    if turns < 3:
        return None
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
    # Use business-local "today" so date math matches the caller's day, not UTC's
    # (which is already tomorrow on the US west coast after ~5pm).
    today = business_local_now(biz).date()
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
        "(5) time — copy the agreed clock time WITH its am/pm period exactly as spoken, "
        "e.g. '3 PM', '9:30 AM', '12 PM' for noon; do NOT convert to 24-hour yourself. "
        "NEVER put a stylist name in the time field, "
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
            model=VOICE_LLM_MODEL,
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


def _strip_message_directive_for_voice(ai_text: str) -> str:
    """Remove a MESSAGE:... directive line so it is never read aloud by TTS."""
    if not ai_text or "MESSAGE:" not in ai_text.upper():
        return (ai_text or "").strip()
    cleaned = re.sub(r"(?is)\s*MESSAGE:\s*[^\n]+", "", ai_text).strip()
    return cleaned if cleaned else (ai_text or "").strip()


def _store_caller_message(call_data: dict, body: str) -> bool:
    """Persist a caller's message (from a MESSAGE: directive) so it appears in the
    dashboard. Caller name comes from caller-memory, phone from the live call. Graceful:
    never raises into the voice turn."""
    body = (body or "").strip()
    if not body:
        return False
    client_id = str(call_data.get("client_id") or "").strip() or None
    caller_mem = call_data.get("caller_memory") or {}
    name = (caller_mem.get("name") or "").strip()
    phone = (call_data.get("from_number") or "").strip()
    low = body.lower()
    urgency = (
        "high"
        if any(w in low for w in ("urgent", "emergency", "asap", "right away"))
        else "normal"
    )
    data = {
        "caller_name": name,
        "caller_phone": phone,
        "message": body[:2000],
        "urgency": urgency,
        "status": "unread",
    }
    try:
        if runtime.USE_DB:
            database.db_messages_insert(data, client_id=client_id)
        else:
            data["id"] = len(runtime.messages) + 1
            data["created_at"] = datetime.now().isoformat()
            runtime.messages.append(data)
        return True
    except Exception as e:
        logger.warning("store_caller_message failed: %s", e, exc_info=True)
        return False


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


def _stylists_offering_service(biz: dict, service_name: Optional[str]) -> list:
    """Names of stylists who provide the given service (their service_ids include it, or an
    empty service_ids means they do everything). Falls back to all stylists when the service
    is unknown or none match."""
    staff_rows = [s for s in (biz.get("staff") or []) if (s.get("name") or "").strip()]
    all_names = [(s.get("name") or "").strip() for s in staff_rows if (s.get("name") or "").strip()]
    if not service_name:
        return all_names
    svc_id = None
    for s in config_service._normalize_service_entries(biz.get("services") or []):
        if (s.get("name") or "").strip().lower() == service_name.strip().lower():
            svc_id = (s.get("id") or "").strip()
            break
    matched = []
    for st in staff_rows:
        nm = (st.get("name") or "").strip()
        if not nm:
            continue
        ids = st.get("service_ids") or []
        if not ids or (svc_id and svc_id in ids):
            matched.append(nm)
    return matched or all_names


def _staff_offers_service(biz: dict, staff_row: dict, service_name: Optional[str]) -> bool:
    """True if this stylist provides the service. Empty service_ids = does everything. An
    unknown/unmatched service is NOT blocked (we can't prove it isn't offered)."""
    if not service_name:
        return True
    ids = staff_row.get("service_ids") or []
    if not ids:
        return True
    svc_id = None
    for s in config_service._normalize_service_entries(biz.get("services") or []):
        if (s.get("name") or "").strip().lower() == service_name.strip().lower():
            svc_id = (s.get("id") or "").strip()
            break
    if not svc_id:
        return True
    return svc_id in ids


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

    service_name, service_required = booking_service._normalize_service_choice_for_booking(
        booking.get("reason"), biz
    )
    # DIAGNOSTIC: pinpoint why the service is (re)asked — what was captured vs the menu,
    # and whether the conversation already indicates a service the matcher is missing.
    try:
        import booking_fields as _bf

        _ctx_dbg = booking_context_from_business(biz)
        system_info(
            "booking_service_check",
            service_required=service_required,
            reason_raw=(booking.get("reason") or "")[:40],
            normalized_service=service_name or "",
            service_resolved_in_convo=service_choice_resolved(conversation_history, _ctx_dbg),
            last_user_named_service=_bf.user_indicated_service_name(user_text, _ctx_dbg.service_names),
            menu=", ".join(sorted(_ctx_dbg.service_names))[:120],
            user_text_tail=(user_text or "")[-60:],
        )
    except Exception:
        pass

    booking_date = (booking.get("date") or "").strip()
    if booking_date:
        try:
            from business_hours import is_past_closing_for_date, same_day_after_hours_message

            target = date.fromisoformat(booking_date)
            if is_past_closing_for_date(biz, target):
                return False, same_day_after_hours_message(biz), staff_id, None
        except ValueError:
            pass
        # Shop-wide closure: never book on a closed date, regardless of stylist.
        import staff_schedule

        closed_msg = staff_schedule.shop_closure_message(biz.get("closures"), booking_date)
        if closed_msg:
            return False, closed_msg, staff_id, None

    ctx = booking_context_from_business(biz)
    service_choices = ", ".join(
        (s.get("name") or "").strip()
        for s in config_service._normalize_service_entries(biz.get("services") or [])[:5]
        if (s.get("name") or "").strip()
    )
    # SERVICE FIRST — get the service before the stylist. Trust a service that normalized to a
    # real menu item (the extraction only sets it when the caller named one); no redundant
    # re-confirm (which previously caused loops when STT phrasing differed, e.g. "shortcut").
    if service_required and not service_name:
        msg = service_prompt_message(
            staff_name="",  # don't tie to a stylist yet — the stylist comes after the service
            service_choices=service_choices,
            already_asked=assistant_asked_service_recently(conversation_history),
        )
        return False, msg, staff_id, None

    # THEN STYLIST — suggest only the stylists who provide the chosen service.
    if staff_rows and not staff_id:
        no_pref = any(p in user_text.lower() for p in _STYLIST_NO_PREF_PHRASES)
        if not (_caller_indicated_stylist_choice(user_text, biz) and no_pref):
            choices = ", ".join(_stylists_offering_service(biz, service_name)[:5])
            msg = (
                "Great — which stylist would you like to see?"
                + (f" For that, we have {choices}." if choices else "")
                + " You can also say anyone if you have no preference."
            )
            return False, msg, None, None
    if (
        staff_id
        and _staff_choice_required(biz)
        and not _caller_indicated_stylist_choice(user_text, biz)
    ):
        choices = ", ".join(_stylists_offering_service(biz, service_name)[:5])
        msg = (
            "Before I lock this in, which stylist would you like?"
            + (f" For that service we have {choices}." if choices else "")
            + " Or say anyone if you have no preference."
        )
        return False, msg, None, None

    # Hard check: the chosen stylist must actually offer the chosen service. Applies to changes
    # too (e.g. caller keeps the stylist but switches to a service that stylist doesn't do).
    if staff_id and service_name:
        srow = next((s for s in staff_rows if str(s.get("id")) == str(staff_id)), None)
        if srow is not None and not _staff_offers_service(biz, srow, service_name):
            name = (srow.get("name") or "").strip() or "That stylist"
            alt = ", ".join(_stylists_offering_service(biz, service_name)[:5])
            msg = (
                f"{name} doesn't do {service_name}. "
                + (f"For {service_name} you can book {alt}. " if alt else "")
                + "Would you like one of them, or a different service?"
            )
            return False, msg, staff_id, service_name

    # Backstop: never book a stylist on a day/time they don't work, even if the AI tried to.
    if staff_id and booking_date:
        srow = next((s for s in staff_rows if str(s.get("id")) == str(staff_id)), None)
        if srow:
            import staff_schedule

            unavailable = staff_schedule.staff_unavailable_message(
                srow, booking_date, (booking.get("time") or "").strip()
            )
            if unavailable:
                return False, unavailable, staff_id, service_name

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
        if not booking_service.reserve_slot(date, time, apt_id, duration_min, staff_key):
            # Concurrent booking won the slot between our availability check and reserve.
            if runtime.USE_DB:
                try:
                    database.db_appointments_update(apt_id, status="cancelled", client_id=cid_for_slot)
                except Exception:
                    pass
            booking_service._invalidate_booked_slots_cache()
            system_info(
                "booking_create_failed_slot_taken_race",
                apt_id=apt_id, date=date, time=time, client_id=cid_for_slot,
            )
            return None
    appointment_data["id"] = apt_id
    appointment_data.setdefault("created_at", datetime.now().isoformat())
    system_info(
        "booking_created_pending_customer",
        apt_id=apt_id,
        client_id=appointment_data.get("client_id") or "(request_context)",
        name=name,
        date=date,
        time=time,
        # DIAGNOSTIC: the exact time string the model emitted, before normalization.
        # If a caller asks for "2 PM" but this shows time_raw="12:00", the model
        # mis-converted to 24h; if time_raw="2 PM" and time="14:00", normalization is fine.
        # This is the line to grep (event=booking_created_pending_customer) if a stored
        # time is ever wrong. Logs are ephemeral on the host, so check within retention.
        time_raw=time_raw or None,
        time_changed_by_normalize=(time_raw or "").strip() != time,
        staff_id=staff_key,
        slot_reserved_immediately=reserve_slot_immediately,
    )
    return appointment_data


def _send_booking_confirmation_sms(
    apt: dict, call_data: dict, cid: Optional[str], call_sid: Optional[str]
) -> str:
    """Send the post-booking confirmation SMS for a freshly-created appointment and update
    caller memory. Returns the caller-facing AI text describing what happened. Shared by the
    live voice booking path and the end-of-call reconciliation backstop."""
    thanks_msg = booking_service._format_appointment_details_confirmation_sms(apt)
    to_number_sms = (
        (call_data.get("from_number") or "").strip()
        or (apt.get("phone") or "").strip()
        or ""
    )
    from_number_sms = (call_data.get("to_number") or "").strip() or None
    if not from_number_sms and cid and runtime.USE_DB:
        tenant_row = database.db_tenant_get_by_client_id(cid)
        if tenant_row:
            from_number_sms = (tenant_row.get("twilio_phone_number") or "").strip()
            sms_info("confirmation_sms_from_tenant_lookup", client_id=cid)
        else:
            sms_info("confirmation_sms_tenant_missing_for_from_override", client_id=cid)
    if not from_number_sms:
        from_number_sms = booking_service._tenant_sms_from_number()
    sms_info(
        "post_booking_confirmation_dispatch",
        client_id=cid,
        to_set=bool(to_number_sms),
        from_set=bool(from_number_sms),
    )
    if to_number_sms:
        if runtime.USE_DB and cid and cid != "default":
            database.db_sms_consent_record(
                to_number_sms,
                cid,
                "voice_booking",
                detail={"appointment_id": apt.get("id")},
            )
        ok = sms_service.send_sms(
            to_number_sms, thanks_msg, from_override=from_number_sms or None
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
                    database.db_sms_session_upsert(
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
            "last_service": ((apt.get("reason") or "").strip()[:120] or None),
        }
        em_patch = (apt.get("email") or "").strip()
        if em_patch:
            dp["email_on_file"] = em_patch
        dp = {k: v for k, v in dp.items() if v}
        try:
            caller_memory.update_caller_memory(
                fn_mem,
                name=(apt.get("name") or "").strip() or None,
                last_reason="appointment details texted (pending SMS confirmation)",
                increment_count=False,
                data_patch=dp if dp else None,
            )
            if call_sid:
                voice_service._merge_call_session(
                    call_sid,
                    {"caller_memory": caller_memory.get_caller_memory(fn_mem)},
                )
        except Exception:
            pass
    return ai_text


def reconcile_booking_at_call_end(
    call_data: dict, call_sid: Optional[str] = None
) -> bool:
    """End-of-call safety net: if the transcript shows the caller agreed to a booking but no
    appointment was created during the call (e.g. the model never emitted the BOOKING: marker,
    or the caller hung up mid-turn), try once to extract + validate + create it here.

    Returns True only when an appointment is actually created (and the confirmation SMS sent).
    Returns False when there is nothing to book, the details are incomplete, or the schedule
    backstop rejects it (e.g. a stylist on a day they don't work) — in which case the call
    correctly falls through to lead capture. Never books past the stylist/shop schedule."""
    if call_data.get("appointment_created"):
        return False
    history = call_data.get("conversation_history")
    if not _conversation_suggests_booking(history):
        return False
    if not config_service.staff_roster_ready_for_booking(config_service.get_business_info()):
        return False
    cid = (call_data.get("client_id") or "").strip() or None
    call_sid = call_sid or call_data.get("call_sid")
    if cid:
        database.set_request_client_id(cid)
    try:
        booking = _extract_booking_line_from_conversation(
            history or [], caller_memory=call_data.get("caller_memory")
        )
    except Exception as e:
        logger.warning("reconcile_extract_failed: %s", e, exc_info=True)
        return False
    if not booking:
        return False
    from_num = (call_data.get("from_number") or "").strip()
    if from_num:
        booking["phone"] = (booking.get("phone") or "").strip() or from_num
    ok_booking, fail_msg, _, canonical_service = _validate_booking_requirements(
        booking, conversation_history=history
    )
    if not ok_booking:
        # The schedule backstop or a missing-required-field check rejected it. Do NOT book;
        # log so the shop can see a caller tried an unavailable slot (e.g. stylist off that day).
        system_info(
            "reconcile_booking_rejected",
            call_sid=call_sid or "",
            client_id=cid or "",
            reason=(fail_msg or "requirements_not_met")[:120],
        )
        return False
    if canonical_service:
        booking["reason"] = canonical_service
    apt = _create_appointment_from_booking(
        booking,
        client_id_override=cid,
        reserve_slot_immediately=False,
        caller_memory=call_data.get("caller_memory"),
    )
    if not apt:
        system_info(
            "reconcile_booking_not_created",
            call_sid=call_sid or "",
            client_id=cid or "",
        )
        return False
    call_data["appointment_created"] = True
    if not (apt.get("phone") or "").strip() and from_num:
        apt["phone"] = from_num
        if runtime.USE_DB and apt.get("id"):
            try:
                database.db_appointments_update(apt["id"], phone=apt["phone"])
            except Exception:
                pass
    _send_booking_confirmation_sms(apt, call_data, cid, call_sid)
    system_info(
        "reconcile_booking_created",
        call_sid=call_sid or "",
        client_id=cid or "",
        apt_id=apt.get("id"),
        date=apt.get("date"),
        time=apt.get("time"),
    )
    return True


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


# ===== AI conversation turn (the voice/SMS response generator) =====

# Honest reply when a caller asks for a human but no transfer number is configured.
# Never let the AI claim to be a person — offer a callback/message instead.
# We already have the caller's number from caller ID, so don't ask for it here.
_NO_TRANSFER_FALLBACK_TEXT = (
    "I'm the AI receptionist, so I can't put a person on the line right now—but I can take "
    "a message and have the team call you back. What's it regarding?"
)


async def generate_response_async(
    call_sid: str, call_data: dict, detected_lang: str, base_url: str
):
    """
    Background task to generate GPT response and TTS audio.
    Updates runtime.call_store.response_status when ready.
    """
    try:
        # Keep tenant context so SMS and DB use correct client_id (async runs outside request)
        database.set_request_client_id(call_data.get("client_id") or database._client_id())
        fn_refresh = (call_data.get("from_number") or "").strip()
        if fn_refresh:
            call_data["caller_memory"] = caller_memory.refresh_caller_memory_for_prompt(
                fn_refresh, call_data.get("client_id")
            )
        voice_info(
            "generate_response_start",
            call_sid=call_sid,
            from_number=call_data.get("from_number") or None,
            client_id=call_data.get("client_id") or None,
        )
        # Diagnostic (only emitted when OBS_TRACE_TRANSCRIPT=1): the exact date + per-stylist
        # schedule the AI is reasoning over, so a wrong "tomorrow" or a misattributed stylist
        # schedule is visible in the logs instead of inferred.
        try:
            import staff_schedule as _ss

            _biz = config_service.get_business_info()
            _tz = business_local_now(_biz)
            _roster = "; ".join(
                f"{(s.get('name') or '?').strip()}="
                + (",".join(_ss.normalize_working_days(s.get("working_days"))) or "any")
                for s in (_biz.get("staff") or [])
                if (s.get("name") or "").strip()
            )
            voice_transcript(
                "booking_debug_context",
                call_sid=call_sid,
                text=(
                    f"model={VOICE_LLM_MODEL} tz={getattr(_tz.tzinfo, 'key', _tz.tzinfo)} "
                    f"today={_tz.strftime('%A')} {_tz.date()} "
                    f"tomorrow={(_tz + timedelta(days=1)).strftime('%A')} {(_tz + timedelta(days=1)).date()} "
                    f"hours=[{(_biz.get('hours') or '')[:60]}] "
                    f"closures={(_biz.get('closures') or [])[:15]} | roster: {_roster}"
                ),
            )
        except Exception:
            pass

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
        # Cap history sent to GPT to the recent tail — long calls would otherwise grow
        # the prompt (and token cost) unbounded turn over turn. The system prompt above
        # carries the durable context (business info, booked slots, caller memory).
        messages.extend(call_data["conversation_history"][-16:])
        nudge = _voice_booking_nudge_message(call_data["conversation_history"])
        if nudge:
            messages.append({"role": "system", "content": nudge})
            voice_info(
                "voice_booking_nudge_injected",
                call_sid=call_sid,
                client_id=str(call_data.get("client_id") or ""),
                user_turns=_count_booking_user_turns(call_data["conversation_history"]),
            )

        # Run on a worker thread: the OpenAI SDK call is blocking, and this
        # coroutine runs as a tracked task on the event loop. Calling it inline
        # would stall every concurrent call's loop work for the request's
        # duration. (The booking-extraction call below is threaded for the same
        # reason.) A hung request is bounded by the client timeout in runtime.py.
        ai_response = await asyncio.to_thread(
            runtime.client.chat.completions.create,
            model=VOICE_LLM_MODEL,
            messages=messages,
            temperature=0.8,
            max_tokens=200,
            stream=False,
        )

        ai_text = ai_response.choices[0].message.content
        voice_debug("gpt_reply", call_sid=call_sid, reply_preview=(ai_text or "")[:80])
        # Full AI reply (incl. any BOOKING marker) when OBS_TRACE_TRANSCRIPT=1 — pairs with the
        # caller_said lines so the whole conversation is reconstructable from the logs.
        voice_transcript("ai_said", call_sid=call_sid, text=ai_text or "")
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
            if not config_service.staff_roster_ready_for_booking():
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
                        # DIAGNOSTIC: what service/stylist did the extraction capture?
                        service_captured=(booking.get("reason") or "")[:40],
                        stylist_captured=(booking.get("staff") or "")[:40],
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
                                    database.db_appointments_update(
                                        apt["id"], phone=apt["phone"]
                                    )
                                except Exception:
                                    pass
                        ai_text = _send_booking_confirmation_sms(
                            apt, call_data, cid, call_sid
                        )
                    else:
                        ctx = booking_context_from_business(config_service.get_business_info())
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
                "I haven't locked anything in just yet—I want to make sure I've got it right. "
                "Can you confirm the service, day, and time you'd like? Then I'll text you to confirm."
            )

        # Never send BOOKING: machine line to TTS or conversation history
        ai_text = _strip_booking_directive_for_voice(ai_text or "")
        if not ai_text:
            ai_text = "Thanks—we've noted that. Let us know if you need anything else."

        # Caller wants to leave a message — capture it, then strip the directive from speech.
        message_body = voice_service.parse_message_directive(ai_text)
        if message_body:
            stored = _store_caller_message(call_data, message_body)
            ai_text = _strip_message_directive_for_voice(ai_text)
            system_info(
                "voice_message_captured",
                call_sid=call_sid,
                client_id=str(call_data.get("client_id") or ""),
                stored=stored,
                msg_len=len(message_body),
            )
            if not ai_text:
                ai_text = "Got it—I've passed your message along to the team. Anything else I can help with?"

        # Honest fallback: the caller asked for a human earlier (flagged in the utterance
        # path) but no transfer number is configured — replace the reply so the AI never
        # pretends to be a person; offer a callback/message instead.
        if call_data.pop("forward_unavailable", False):
            if not (config_service.get_business_info().get("forwarding_phone") or "").strip():
                ai_text = _NO_TRANSFER_FALLBACK_TEXT

        # Add AI response to conversation
        ai_message = {"role": "assistant", "content": ai_text}
        call_data["conversation_history"].append(ai_message)
        # Merge into the latest session under the per-call lock — a full overwrite here
        # would clobber a caller turn that arrived while we were generating (the AI would
        # then re-ask for info already given), which surfaces under concurrent-call load.
        await voice_service.persist_generated_session_locked(call_sid, call_data)

        # Pro: Staff transfer - AI may respond with TRANSFER_TO: Name
        transfer_name = voice_service.parse_transfer_to(ai_text)
        if transfer_name:
            staff_phone = config_service.get_staff_phone_by_name(transfer_name)
            if staff_phone:
                voice_forward(
                    "staff_transfer_by_name",
                    call_sid=call_sid,
                    client_id=str(call_data.get("client_id") or ""),
                    forward_kind="staff_named",
                    staff_name=transfer_name,
                )
                call_data["outcome"] = "forwarded"
                voice_service.call_log_set_outcome(call_sid, "forwarded")
                runtime.call_store.response_status[call_sid] = {
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
        if voice_service.should_forward_to_human(
            "",
            ai_text,
            call_sid=call_sid,
            client_id=str(call_data.get("client_id") or ""),
        ):
            forwarding_phone = config_service.get_business_info().get("forwarding_phone")
            if forwarding_phone:
                voice_forward(
                    "ai_transfer_intent_in_reply",
                    call_sid=call_sid,
                    client_id=str(call_data.get("client_id") or ""),
                    forward_kind="fallback",
                    has_fallback_configured=True,
                )
                call_data["outcome"] = "forwarded"
                voice_service.call_log_set_outcome(call_sid, "forwarded")
                runtime.call_store.response_status[call_sid] = {
                    "status": "forward",
                    "audio_url": None,
                    "ai_text": ai_text,
                    "forwarding_phone": forwarding_phone,
                }
                return
            # AI reply implied a transfer but there's no number — speak the honest line.
            ai_text = _NO_TRANSFER_FALLBACK_TEXT

        # Generate TTS audio URL
        ai_text_encoded = quote(ai_text)
        tts_audio_url = f"{base_url}/api/phone/tts-audio?text={ai_text_encoded}&voice={config_service.get_tts_voice()}"

        # Mark as ready
        runtime.call_store.response_status[call_sid] = {
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
        fallback_encoded = quote(voice_service.TTS_FALLBACK_TEXT)
        fallback_tts_url = f"{base_url}/api/phone/tts-audio?text={fallback_encoded}&voice={config_service.get_tts_voice()}"
        runtime.call_store.response_status[call_sid] = {
            "status": "ready",
            "audio_url": fallback_tts_url,
            "ai_text": voice_service.TTS_FALLBACK_TEXT,
            "error": type(e).__name__,
        }
        voice_info(
            "gpt_response_fallback_tts",
            call_sid=call_sid,
            client_id_prefix=str(call_data.get("client_id") or "")[:12],
        )
    finally:
        await voice_service.persist_generated_session_locked(call_sid, call_data)
