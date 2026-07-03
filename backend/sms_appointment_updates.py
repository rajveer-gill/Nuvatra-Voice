"""Parse and persist appointment corrections from inbound SMS (name, time, date, service)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional, Tuple

DetailUpdateResult = Tuple[Optional[dict], list[str]]

from observability import name_initial_for_log, sms_info, sms_trace

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_NAME_PATTERNS = (
    re.compile(r"(?:my\s+)?name\s+is\s+([A-Za-z][A-Za-z'\-\s]{1,48})", re.I),
    re.compile(r"(?:it'?s|i'?m|i am)\s+([A-Za-z][A-Za-z'\-\s]{1,48})(?:\s*,|\s+and\b|\s+not\b|$)", re.I),
    re.compile(r"call\s+me\s+([A-Za-z][A-Za-z'\-\s]{1,48})", re.I),
)
_TIME_PATTERNS = (
    re.compile(
        r"(?:can we|could we|let'?s)\s+(?:do|make it|switch to|change to|move to)\s+"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.?\s*m\.?|p\.?\s*m\.?)?\b",
        re.I,
    ),
    re.compile(
        r"(?:change|move|switch|make it|update)\s+(?:the\s+)?(?:time\s+)?(?:to\s+)?"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.?\s*m\.?|p\.?\s*m\.?)?\b",
        re.I,
    ),
    re.compile(
        r"(?:at|to)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.?\s*m\.?|p\.?\s*m\.?)?"
        r"\s*(?:instead|actually|please|works|ok)?",
        re.I,
    ),
    re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm|a\.?\s*m\.?|p\.?\s*m\.?)\b", re.I),
    re.compile(r"\b(\d{1,2})\s*(am|pm|a\.?\s*m\.?|p\.?\s*m\.?)\b", re.I),
)
_DATE_ISO_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_DATE_RELATIVE_RE = re.compile(r"\b(today|tomorrow)\b", re.I)

# Natural-language date parsing (so "July 8th", "the 8th", "next Monday" work, not just ISO).
_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_WEEKDAY_NUM = {
    "monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
_MONTH_NAME = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_MONTH_DAY_RE = re.compile(rf"\b{_MONTH_NAME}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)
_DAY_MONTH_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+of\s+{_MONTH_NAME}\b", re.I)
_ORDINAL_DAY_RE = re.compile(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b", re.I)
_WEEKDAY_RE = re.compile(
    r"\b(?:next|this|coming|on)?\s*"
    r"(monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thur|thu|friday|fri|saturday|sat|sunday|sun)\b",
    re.I,
)
_SERVICE_PATTERNS = (
    re.compile(
        r"(?:change|switch|update)\s+(?:the\s+)?service\s+(?:to\s+)?(?:a\s+)?"
        r"([A-Za-z][A-Za-z0-9'\-\s]{2,48})",
        re.I,
    ),
    re.compile(r"service\s+(?:should be|is)\s+([A-Za-z][A-Za-z0-9'\-\s]{2,48})", re.I),
)
_CONFIRM_TOKENS = frozenset(
    {
        "yes",
        "yep",
        "yeah",
        "yup",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "correct",
        "perfect",
        "great",
        "approved",
    }
)
_CONFIRM_PHRASES = (
    "looks good",
    "look good",
    "that's right",
    "thats right",
    "all good",
    "sounds good",
    "sounds great",
    "that works for me",
    "that works",
    "thats correct",
    "that's correct",
)


def parse_email_from_sms(body: str) -> Optional[str]:
    m = _EMAIL_RE.search(body or "")
    return m.group(0).strip() if m else None


def _clean_parsed_name(raw: str) -> Optional[str]:
    name = (raw or "").strip()
    name = re.sub(r"[,.\s]+$", "", name)
    name = re.split(r"\s+not\s+", name, maxsplit=1, flags=re.I)[0].strip()
    name = re.split(r"\s+and\s+my\s+", name, maxsplit=1, flags=re.I)[0].strip()
    if len(name) < 2 or len(name) > 50:
        return None
    if not re.match(r"^[A-Za-z]", name):
        return None
    return name


def parse_name_from_sms(body: str, *, current_name: str = "") -> Optional[str]:
    """Best-effort name from correction texts like 'my name is Raj, not Jake'."""
    text = (body or "").strip()
    if not text:
        return None
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            cleaned = _clean_parsed_name(m.group(1))
            if cleaned:
                cur = (current_name or "").strip().lower()
                if cleaned.lower() != cur:
                    return cleaned
    return None


def _is_likely_sms_confirmation_body(body: str) -> bool:
    """True when the message is only confirming details (not requesting a change)."""
    if not body or len(body) > 80:
        return False
    b = body.lower().strip()
    if b in _CONFIRM_TOKENS:
        return True
    for phrase in _CONFIRM_PHRASES:
        if phrase in b:
            return True
    tokens = set(re.findall(r"[a-z0-9']+", b))
    if tokens & _CONFIRM_TOKENS and not any(
        pat.search(body or "") for pat in _TIME_PATTERNS[:3]
    ):
        return True
    return False


def _time_to_minutes(raw: str, *, reference_time: str = "") -> int:
    """Parse time string to minutes since midnight (salon-style AM/PM when omitted)."""
    if not raw:
        return 0
    text = (raw or "").strip()
    upper = text.upper()
    meridian: Optional[str] = None
    if re.search(r"\bP\.?\s*M\.?\b", upper) or re.search(r"\bPM\b", upper):
        meridian = "pm"
    elif re.search(r"\bA\.?\s*M\.?\b", upper) or re.search(r"\bAM\b", upper):
        meridian = "am"
    cleaned = re.sub(r"(?i)\s*(a\.?\s*m\.?|p\.?\s*m\.?)\s*$", "", text).strip()
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
        ref_mins = _time_to_minutes(reference_time) if reference_time else None
        if ref_mins is not None and ref_mins >= 12 * 60 and 1 <= h <= 11:
            h += 12
        elif h == 12:
            pass
        elif 1 <= h <= 8:
            h += 12
    return h * 60 + m


def normalize_time_to_hhmm(raw: str, *, reference_time: str = "") -> str:
    if not (raw or "").strip():
        return ""
    mins = _time_to_minutes(raw, reference_time=reference_time)
    h, m = divmod(mins, 60)
    return f"{h:02d}:{m:02d}"


def _build_time_candidate(hour: str, minute: Optional[str], meridian: Optional[str]) -> str:
    mm = (minute or "00").zfill(2) if minute else "00"
    mer = (meridian or "").strip()
    if mer:
        mer_clean = re.sub(r"[^a-z]", "", mer.lower())
        if mer_clean.startswith("p"):
            return f"{hour}:{mm} pm"
        if mer_clean.startswith("a"):
            return f"{hour}:{mm} am"
    return f"{hour}:{mm}" if minute else hour


def parse_time_from_sms(body: str, *, current_time: str = "") -> Optional[str]:
    """Return HH:MM when the customer asks to change appointment time."""
    text = (body or "").strip()
    if not text or _is_likely_sms_confirmation_body(text):
        return None
    current_hhmm = normalize_time_to_hhmm(current_time, reference_time=current_time)
    for pat in _TIME_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        groups = m.groups()
        hour = groups[0]
        minute = groups[1] if len(groups) > 1 else None
        meridian = groups[2] if len(groups) > 2 else None
        candidate = _build_time_candidate(hour, minute, meridian)
        parsed = normalize_time_to_hhmm(candidate, reference_time=current_hhmm or current_time)
        if parsed and parsed != current_hhmm:
            return parsed
    return None


def _future_date_for_month_day(base: date, month: int, day: int) -> Optional[date]:
    """The next occurrence of month/day on or after base (this year, else next year)."""
    for yr in (base.year, base.year + 1):
        try:
            d = date(yr, month, day)
        except ValueError:
            return None
        if d >= base:
            return d
    return None


def _future_day_of_month(base: date, day: int) -> Optional[date]:
    """Nearest date on or after base that falls on the given day-of-month."""
    y, m = base.year, base.month
    for _ in range(14):
        try:
            d = date(y, m, day)
        except ValueError:
            d = None
        if d and d >= base:
            return d
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return None


def parse_date_from_sms(
    body: str, *, current_date: str = "", today: Optional[date] = None
) -> Optional[str]:
    """Best-effort date from a change text. Handles ISO (2026-07-08), today/tomorrow, month +
    day ("July 8th", "the 8th of July"), a bare ordinal ("the 8th"), and weekdays ("next
    Monday"). Relative dates are computed from `today` (business-local when supplied)."""
    text = (body or "").strip()
    if not text or _is_likely_sms_confirmation_body(text):
        return None
    base = today or date.today()
    cur = (current_date or "").strip()

    def _result(d: Optional[date]) -> Optional[str]:
        if not d:
            return None
        iso = d.isoformat()
        return iso if iso != cur else None

    iso = _DATE_ISO_RE.search(text)
    if iso:
        try:
            return _result(date.fromisoformat(iso.group(1)))
        except ValueError:
            return None

    rel = _DATE_RELATIVE_RE.search(text)
    if rel:
        d = base + timedelta(days=1) if rel.group(1).lower() == "tomorrow" else base
        return _result(d)

    # Month + day, either order ("July 8th" / "8th of July").
    m = _MONTH_DAY_RE.search(text)
    month = day = None
    if m:
        month, day = _MONTH_ABBR.get(m.group(1)[:3].lower()), int(m.group(2))
    else:
        dm = _DAY_MONTH_RE.search(text)
        if dm:
            month, day = _MONTH_ABBR.get(dm.group(2)[:3].lower()), int(dm.group(1))
    if month and day:
        return _result(_future_date_for_month_day(base, month, day))

    od = _ORDINAL_DAY_RE.search(text)
    if od:
        return _result(_future_day_of_month(base, int(od.group(1))))

    wd = _WEEKDAY_RE.search(text)
    if wd:
        target = _WEEKDAY_NUM.get(wd.group(1).lower())
        if target is not None:
            ahead = (target - base.weekday()) % 7
            if ahead == 0:  # "Monday" means the upcoming Monday, not today
                ahead = 7
            return _result(base + timedelta(days=ahead))
    return None


def parse_service_from_sms(
    body: str, *, current_service: str = "", known_services: Optional[list[str]] = None
) -> Optional[str]:
    text = (body or "").strip()
    if not text or _is_likely_sms_confirmation_body(text):
        return None
    if re.search(r"\bname\s+is\b", text, re.I):
        return None
    cur = (current_service or "").strip().lower()
    # Match against the shop's actual menu first — real texts say "make it a long cut" or
    # "long cut instead", not the rigid "change service to Long Cut". Longest name first so a
    # multi-word service ("Long Cut") wins over a shorter substring ("Cut").
    for svc in sorted(
        (s.strip() for s in (known_services or []) if (s or "").strip()),
        key=len,
        reverse=True,
    ):
        if svc.lower() == cur:
            continue
        if re.search(r"\b" + re.escape(svc) + r"\b", text, re.I):
            return svc
    skip_words = {
        "time",
        "date",
        "tomorrow",
        "today",
        "appointment",
        "the",
        "a",
        "an",
    }
    for pat in _SERVICE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        service = (m.group(1) or "").strip()
        service = re.sub(r"[,.\s]+$", "", service)
        if len(service) < 3 or service.lower() in skip_words:
            continue
        if service.lower() != cur:
            return service
    return None


def parse_stylist_from_sms(
    body: str, *, current_stylist: str = "", known_stylists: Optional[list[str]] = None
) -> Optional[str]:
    """Best-effort stylist request from a change text ("switch me to Andrew", "can I see Tom
    instead"). Matches a name from the shop's roster (longest-first) that differs from the
    current stylist. Returns the matched roster name, or None."""
    text = (body or "").strip()
    if not text or _is_likely_sms_confirmation_body(text):
        return None
    # "my name is Andrew" is the CUSTOMER's own name, not a request to switch stylists.
    if re.search(r"\bmy\s+name\s+is\b", text, re.I):
        return None
    cur = (current_stylist or "").strip().lower()
    for name in sorted(
        (n.strip() for n in (known_stylists or []) if (n or "").strip()),
        key=len,
        reverse=True,
    ):
        if name.lower() == cur:
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", text, re.I):
            return name
    return None


def apply_sms_appointment_detail_updates_from_bodies(
    bodies: list[str],
    apt: Optional[dict],
    *,
    client_id: str,
    from_number: str,
    db_appointments_update,
    db_appointments_get_by_id,
    update_caller_memory,
    db_appointments_update_active_name_by_phone=None,
    system_info,
    logger,
    known_services: Optional[list[str]] = None,
    known_staff: Optional[list[dict]] = None,
    service_id_by_name: Optional[dict] = None,
    business_info: Optional[dict] = None,
    rejection_out: Optional[dict] = None,
) -> DetailUpdateResult:
    """Apply name/time/date/service/stylist from the latest values across recent inbound SMS.

    When a requested stylist change is refused (the stylist doesn't offer the service or is off
    that day), a caller-facing explanation is written to rejection_out["message"] so the SMS
    handler can tell the customer the truth instead of silently keeping the old stylist."""
    if not apt or not apt.get("id"):
        return apt, []
    st = (apt.get("status") or "").strip()
    if st not in ("pending_customer", "pending_review", "accepted"):
        return apt, []
    aid = int(apt["id"])
    prior_name = (apt.get("name") or "").strip()
    prior_time = normalize_time_to_hhmm(
        apt.get("time") or "", reference_time=(apt.get("time") or "")
    )
    prior_date = (apt.get("date") or "").strip()
    prior_service = (apt.get("reason") or "").strip()
    # Staff roster maps for resolving a "switch me to Andrew" text to a staff_id.
    staff_by_name: dict[str, dict] = {}
    staff_by_id: dict[str, dict] = {}
    for row in known_staff or []:
        nm = (row.get("name") or "").strip()
        if nm:
            staff_by_name[nm.lower()] = row
        sid = str(row.get("id") or "").strip()
        if sid:
            staff_by_id[sid] = row
    staff_names = [(r.get("name") or "").strip() for r in (known_staff or []) if (r.get("name") or "").strip()]
    prior_staff_id = str(apt.get("staff_id") or "").strip()
    prior_stylist_name = (staff_by_id.get(prior_staff_id, {}).get("name") or "").strip()
    # Business-local "today" so "tomorrow"/"next Monday" resolve to the caller's day, not UTC's.
    _sms_today = None
    try:
        import business_hours as _bh

        _sms_today = _bh.business_local_now(business_info or {}).date()
    except Exception:
        _sms_today = None
    latest_name: Optional[str] = None
    latest_time: Optional[str] = None
    latest_date: Optional[str] = None
    latest_service: Optional[str] = None
    latest_stylist: Optional[str] = None
    cur_name = prior_name
    cur_time = prior_time
    user_body_count = sum(1 for b in bodies if (b or "").strip())
    sms_info(
        "sms_detail_updates_scan",
        apt_id=aid,
        client_id=client_id,
        user_body_count=user_body_count,
        prior_name_initial=name_initial_for_log(prior_name),
        apt_status=st,
        prior_time=prior_time or None,
    )
    for body in bodies:
        if not (body or "").strip():
            continue
        nm = parse_name_from_sms(body, current_name=cur_name)
        if nm:
            latest_name = nm
            cur_name = nm
        tm = parse_time_from_sms(body, current_time=cur_time or (apt.get("time") or ""))
        if tm:
            latest_time = tm
            cur_time = tm
        dt = parse_date_from_sms(body, current_date=prior_date, today=_sms_today)
        if dt:
            latest_date = dt
        sv = parse_service_from_sms(
            body, current_service=prior_service, known_services=known_services
        )
        if sv:
            latest_service = sv
        sty = parse_stylist_from_sms(
            body, current_stylist=prior_stylist_name, known_stylists=staff_names
        )
        if sty:
            latest_stylist = sty
    kwargs: dict[str, Any] = {}
    if latest_name:
        kwargs["name"] = latest_name
    if latest_time:
        kwargs["time"] = latest_time
    if latest_date:
        kwargs["date"] = latest_date
    if latest_service:
        kwargs["reason"] = latest_service
    # Stylist change: resolve to a staff_id, but only apply it when the new stylist offers the
    # (effective) service AND works the (effective) day/time — never book an invalid combo.
    stylist_rejected = ""
    if latest_stylist:
        row = staff_by_name.get(latest_stylist.lower())
        new_sid = str((row or {}).get("id") or "").strip()
        if row and new_sid and new_sid != prior_staff_id:
            eff_service = (latest_service or prior_service or "").strip()
            eff_date = (latest_date or prior_date or "").strip()
            eff_time = latest_time or prior_time or ""
            svc_id = (service_id_by_name or {}).get(eff_service.lower())
            ids = row.get("service_ids") or []
            offers = (not eff_service) or (svc_id is None) or (not ids) or (svc_id in ids)
            unavail = None
            if eff_date:
                import staff_schedule

                unavail = staff_schedule.staff_unavailable_message(row, eff_date, eff_time)
            if offers and not unavail:
                kwargs["staff_id"] = new_sid
            else:
                stylist_rejected = "not_offered" if not offers else "unavailable"
                if rejection_out is not None:
                    if not offers:
                        # Who DOES offer the effective service (excluding the refused stylist)?
                        alts = [
                            (r.get("name") or "").strip()
                            for r in (known_staff or [])
                            if (r.get("name") or "").strip()
                            and (r.get("name") or "").strip().lower() != latest_stylist.lower()
                            and (
                                not (r.get("service_ids") or [])
                                or (svc_id and svc_id in (r.get("service_ids") or []))
                            )
                        ]
                        msg = f"{latest_stylist} doesn't do {eff_service}."
                        if alts:
                            msg += f" For {eff_service}, you can book {', '.join(alts[:3])}."
                        msg += " Want one of them, or a different service?"
                    else:
                        msg = (
                            f"{latest_stylist} isn't available that day. "
                            "Want another day, or a different stylist?"
                        )
                    rejection_out["message"] = msg
                    rejection_out["reason"] = stylist_rejected
                sms_info(
                    "sms_stylist_change_rejected",
                    apt_id=aid,
                    client_id=client_id,
                    reason=stylist_rejected,
                    stylist_initial=name_initial_for_log(latest_stylist),
                )
    # Date/time change validation: never move an appointment onto a day the shop is closed
    # (weekend or a shop closure) or a day/time the assigned stylist doesn't work.
    if ("date" in kwargs) or ("time" in kwargs):
        import staff_schedule

        eff_date = latest_date or prior_date
        eff_time = latest_time or prior_time or ""
        eff_row = staff_by_id.get(str(kwargs.get("staff_id") or prior_staff_id))
        closures = (business_info or {}).get("closures") or []
        block_msg = None
        if eff_date:
            if staff_schedule.shop_closure_message(closures, eff_date):
                block_msg = f"We're closed on {staff_schedule.friendly_date(eff_date)}. Want another day?"
            else:
                try:
                    import business_hours as _bh

                    if getattr(_bh.day_slot_for_date(business_info or {}, eff_date), "closed", False):
                        block_msg = (
                            f"We're closed on {staff_schedule.friendly_date(eff_date)}. Want another day?"
                        )
                except Exception:
                    pass
            if not block_msg and eff_row:
                unavail = staff_schedule.staff_unavailable_message(eff_row, eff_date, eff_time)
                if unavail:
                    block_msg = unavail
        if block_msg:
            kwargs.pop("date", None)
            kwargs.pop("time", None)
            if rejection_out is not None and not rejection_out.get("message"):
                rejection_out["message"] = block_msg
                rejection_out["reason"] = "date_unavailable"
            sms_info(
                "sms_date_change_rejected", apt_id=aid, client_id=client_id, eff_date=eff_date or None
            )
    if not kwargs:
        sms_info(
            "sms_detail_updates_no_match",
            apt_id=aid,
            client_id=client_id,
            user_body_count=user_body_count,
            prior_name_initial=name_initial_for_log(prior_name),
        )
        return apt, []
    sms_info(
        "sms_detail_updates_parsed",
        apt_id=aid,
        client_id=client_id,
        will_update_name=bool(latest_name),
        will_update_time=bool(latest_time),
        will_update_date=bool(latest_date),
        will_update_service=bool(latest_service),
        will_update_stylist=bool(kwargs.get("staff_id")),
        stylist_rejected=stylist_rejected or None,
        prior_name_initial=name_initial_for_log(prior_name),
        new_name_initial=name_initial_for_log(latest_name),
        prior_time=prior_time or None,
        new_time=latest_time,
    )
    return apply_sms_appointment_detail_updates(
        " ".join(bodies),
        apt,
        client_id=client_id,
        from_number=from_number,
        db_appointments_update=db_appointments_update,
        db_appointments_get_by_id=db_appointments_get_by_id,
        update_caller_memory=update_caller_memory,
        db_appointments_update_active_name_by_phone=db_appointments_update_active_name_by_phone,
        system_info=system_info,
        logger=logger,
        known_services=known_services,
        _forced_kwargs=kwargs,
    )


def apply_sms_appointment_detail_updates(
    body: str,
    apt: Optional[dict],
    *,
    client_id: str,
    from_number: str,
    db_appointments_update,
    db_appointments_get_by_id,
    update_caller_memory,
    db_appointments_update_active_name_by_phone=None,
    system_info,
    logger,
    known_services: Optional[list[str]] = None,
    _forced_kwargs: Optional[dict[str, Any]] = None,
) -> DetailUpdateResult:
    """
    Persist email/name/time/date/service from SMS before confirm or conversational replies.
    Returns (appointment row, field names that actually changed).
    """
    if not apt or not apt.get("id"):
        return apt, []
    st = (apt.get("status") or "").strip()
    if st not in ("pending_customer", "pending_review", "accepted"):
        return apt, []
    aid = int(apt["id"])
    kwargs: dict[str, Any] = dict(_forced_kwargs or {})
    if not kwargs:
        nm = parse_name_from_sms(body, current_name=(apt.get("name") or ""))
        if nm:
            kwargs["name"] = nm
        tm = parse_time_from_sms(body, current_time=(apt.get("time") or ""))
        if tm:
            kwargs["time"] = tm
        dt = parse_date_from_sms(body, current_date=(apt.get("date") or ""))
        if dt:
            kwargs["date"] = dt
        sv = parse_service_from_sms(
            body, current_service=(apt.get("reason") or ""), known_services=known_services
        )
        if sv:
            kwargs["reason"] = sv
    if not kwargs:
        return apt, []
    prior = {k: (apt.get(k) or "").strip() for k in kwargs}
    if "time" in kwargs:
        prior["time"] = normalize_time_to_hhmm(
            prior.get("time", ""), reference_time=(apt.get("time") or "")
        )
    try:
        updated = db_appointments_update(aid, client_id=client_id, **kwargs)
        if not updated:
            return apt, []
        apt = updated
        try:
            update_caller_memory(
                from_number,
                name=kwargs.get("name") or (apt.get("name") or "").strip() or None,
                increment_count=False,
            )
        except Exception:
            pass
        refreshed = db_appointments_get_by_id(aid, client_id=client_id) or apt
        system_info(
            "inbound_customer_details_updated_from_sms",
            apt_id=aid,
            client_id=client_id,
            fields=list(kwargs.keys()),
        )
        sms_info(
            "sms_detail_updates_applied",
            apt_id=aid,
            client_id=client_id,
            fields=list(kwargs.keys()),
            name_initial=name_initial_for_log(refreshed.get("name")),
            time=refreshed.get("time"),
            date=refreshed.get("date"),
        )
        sms_trace(
            "sms_detail_updates_applied_verbose",
            apt_id=aid,
            client_id=client_id,
            fields=list(kwargs.keys()),
            name_initial=name_initial_for_log(refreshed.get("name")),
        )
        if kwargs.get("name") and callable(db_appointments_update_active_name_by_phone):
            try:
                updated_n = db_appointments_update_active_name_by_phone(
                    from_number,
                    client_id=client_id,
                    name=kwargs["name"],
                    exclude_appointment_id=aid,
                )
                if updated_n:
                    sms_info(
                        "sms_detail_updates_bulk_name_applied",
                        apt_id=aid,
                        client_id=client_id,
                        updated_rows=updated_n,
                        name_initial=name_initial_for_log(kwargs.get("name")),
                    )
            except Exception:
                pass
        changed: list[str] = []
        for k in kwargs:
            new_val = (refreshed.get(k) or "").strip()
            old_val = prior.get(k, "")
            if k == "time":
                new_val = normalize_time_to_hhmm(new_val, reference_time=new_val)
                old_val = normalize_time_to_hhmm(old_val, reference_time=old_val)
            if new_val != old_val:
                changed.append(k)
        return refreshed, changed
    except Exception as e:
        logger.warning("apply_sms_appointment_detail_updates failed apt_id=%s: %s", aid, e, exc_info=True)
        return apt, []
