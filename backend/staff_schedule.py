"""Per-stylist working-day / working-hour / time-off helpers, plus shop closures.

A staff record may carry:
- working_days: list of lowercase day codes (mon..sun) the person works. Empty = no
  constraint (works whenever the shop is open).
- working_hours: optional {day_code: {"start": "HH:MM", "end": "HH:MM"}} narrowing the
  hours on specific days. A day with no entry = full shop hours that day.
- time_off: list of specific ISO dates (YYYY-MM-DD) the person is off (sick/vacation).

The business config may carry:
- closures: list of specific ISO dates the WHOLE shop is closed.

These feed the voice prompt (so the AI knows) and a server-side booking backstop
(reject a booking for a stylist/shop on a day they don't work / are off / are closed).
All list inputs are validated and capped to bound config size and prompt tokens.
"""

from __future__ import annotations

from datetime import date as _date, timedelta
from typing import Iterable, Optional

DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_SET = set(DAY_ORDER)
DAY_LABELS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}

# Cap per-stylist time-off and per-tenant closures lists. Bounds JSONB growth and the
# number of dates that can reach the prompt. A year of dates is far more than realistic.
MAX_DATES = 366
# Only dates within this window from "today" are injected into the prompt (token budget).
PROMPT_HORIZON_DAYS = 120
PROMPT_DATE_CAP = 40


# ----- day-of-week schedule -------------------------------------------------


def normalize_working_days(value) -> list[str]:
    """Lowercase 3-letter day codes, deduped, in Mon..Sun order; drop anything invalid."""
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    seen = set()
    for raw in value:
        d = str(raw).strip().lower()[:3]
        if d in DAY_SET:
            seen.add(d)
    return [d for d in DAY_ORDER if d in seen]


def _to_minutes(hhmm) -> Optional[int]:
    try:
        h, m = str(hhmm).strip().split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h * 60 + m
    return None


def normalize_working_hours(value) -> dict:
    """Keep only {valid_day: {start, end}} with valid HH:MM and start < end."""
    if not isinstance(value, dict):
        return {}
    out: dict = {}
    for raw_day, win in value.items():
        d = str(raw_day).strip().lower()[:3]
        if d not in DAY_SET or not isinstance(win, dict):
            continue
        start, end = _to_minutes(win.get("start")), _to_minutes(win.get("end"))
        if start is None or end is None or start >= end:
            continue
        out[d] = {"start": str(win["start"]).strip(), "end": str(win["end"]).strip()}
    return out


def _fmt_ampm(hhmm: str) -> str:
    mins = _to_minutes(hhmm)
    if mins is None:
        return str(hhmm)
    h, m = divmod(mins, 60)
    ap = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12}:{m:02d} {ap}"


# ----- specific-date helpers (time off / closures) --------------------------


def _parse_iso(value) -> Optional[_date]:
    try:
        return _date.fromisoformat(str(value).strip())
    except (ValueError, AttributeError, TypeError):
        return None


def weekday_code(date_str) -> Optional[str]:
    d = _parse_iso(date_str)
    return DAY_ORDER[d.weekday()] if d else None


def normalize_date_list(value) -> list[str]:
    """Validate ISO dates, dedupe, sort ascending, cap length. Drop anything invalid."""
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    seen = set()
    for raw in value:
        d = _parse_iso(raw)
        if d is not None:
            seen.add(d.isoformat())
    return sorted(seen)[:MAX_DATES]


def _month_day(d: _date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _range_label(a: _date, b: _date) -> str:
    if a == b:
        return _month_day(a)
    if a.month == b.month and a.year == b.year:
        return f"{a.strftime('%b')} {a.day}–{b.day}"
    return f"{_month_day(a)}–{_month_day(b)}"


def collapse_date_ranges(dates: Iterable[str]) -> list[str]:
    """Collapse consecutive ISO dates into 'Jul 1-5' style labels for readable display."""
    parsed = sorted({d for d in (_parse_iso(x) for x in dates) if d is not None})
    if not parsed:
        return []
    out: list[str] = []
    start = prev = parsed[0]
    for d in parsed[1:]:
        if (d - prev).days == 1:
            prev = d
            continue
        out.append(_range_label(start, prev))
        start = prev = d
    out.append(_range_label(start, prev))
    return out


def friendly_date(date_str) -> str:
    """'Friday, July 3' for a spoken/written caller-facing message."""
    d = _parse_iso(date_str)
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}" if d else str(date_str)


def upcoming_dates(dates: Iterable[str], today: Optional[_date] = None) -> list[str]:
    """ISO dates from today..+horizon (sorted, capped) — for the prompt token budget."""
    t = today or _date.today()
    end = t + timedelta(days=PROMPT_HORIZON_DAYS)
    out = []
    for x in sorted(normalize_date_list(list(dates))):
        d = _parse_iso(x)
        if d is not None and t <= d <= end:
            out.append(x)
    return out[:PROMPT_DATE_CAP]


# ----- prompt fragments -----------------------------------------------------


def working_days_prompt_text(staff_row: dict) -> str:
    """Prompt fragment like 'Monday, Tuesday, Friday (Friday 12:00 PM-5:00 PM)'. Empty when no schedule."""
    days = normalize_working_days(staff_row.get("working_days"))
    if not days:
        return ""
    hours = normalize_working_hours(staff_row.get("working_hours"))
    base = ", ".join(DAY_LABELS[d] for d in days)
    extras = [
        f"{DAY_LABELS[d]} {_fmt_ampm(hours[d]['start'])}–{_fmt_ampm(hours[d]['end'])}"
        for d in days
        if d in hours
    ]
    return f"{base} ({'; '.join(extras)})" if extras else base


def time_off_prompt_text(staff_row: dict, today: Optional[_date] = None) -> str:
    """Upcoming time-off as collapsed ranges, e.g. 'Jul 1-5, Aug 12'. Empty when none upcoming."""
    upcoming = upcoming_dates(staff_row.get("time_off") or [], today=today)
    return ", ".join(collapse_date_ranges(upcoming))


def closures_prompt_text(closures, today: Optional[_date] = None) -> str:
    """Upcoming shop closures as collapsed ranges. Empty when none upcoming."""
    upcoming = upcoming_dates(closures or [], today=today)
    return ", ".join(collapse_date_ranges(upcoming))


# ----- booking backstop -----------------------------------------------------


def shop_closure_message(closures, date_str) -> Optional[str]:
    """If the shop is closed on the date, return a caller-facing reason; else None."""
    d = _parse_iso(date_str)
    if d is None:
        return None
    if d.isoformat() in set(normalize_date_list(closures)):
        return (
            f"We're closed on {friendly_date(date_str)}. "
            "Would you like to pick another day?"
        )
    return None


def staff_unavailable_message(
    staff_row: dict, date_str: str, time_str: str = ""
) -> Optional[str]:
    """If the stylist is off the given date (time off), or doesn't work that weekday/time,
    return a caller-facing reason; else None. Time off is checked first."""
    name = (staff_row.get("name") or "").strip() or "That stylist"
    d = _parse_iso(date_str)
    if d is None:
        return None

    if d.isoformat() in set(normalize_date_list(staff_row.get("time_off"))):
        return (
            f"{name} is off on {friendly_date(date_str)}. "
            "Would you like another day, or a different stylist?"
        )

    day = DAY_ORDER[d.weekday()]
    working_days = normalize_working_days(staff_row.get("working_days"))
    if working_days and day not in working_days:
        worked = ", ".join(DAY_LABELS[x] for x in working_days)
        return (
            f"{name} doesn't work on {DAY_LABELS[day]}—{name} works {worked}. "
            "Would you like another day, or a different stylist?"
        )

    hours = normalize_working_hours(staff_row.get("working_hours")).get(day)
    if hours and time_str:
        t = _to_minutes(time_str)
        start, end = _to_minutes(hours["start"]), _to_minutes(hours["end"])
        if t is not None and start is not None and end is not None and not (start <= t < end):
            return (
                f"{name} works {_fmt_ampm(hours['start'])}–{_fmt_ampm(hours['end'])} on "
                f"{DAY_LABELS[day]}. Could we pick a time in that window, or another day?"
            )
    return None


def appointment_conflict(
    staff_row: Optional[dict], closures, date_str: str, time_str: str = ""
) -> Optional[dict]:
    """Short conflict descriptor for the dashboard: {type, label} when an existing
    appointment falls on a closure / the stylist's off date / off weekday / off hours; else None."""
    d = _parse_iso(date_str)
    if d is None:
        return None
    if d.isoformat() in set(normalize_date_list(closures)):
        return {"type": "shop_closed", "label": "Shop closed"}
    if staff_row:
        name = (staff_row.get("name") or "").strip() or "Stylist"
        if d.isoformat() in set(normalize_date_list(staff_row.get("time_off"))):
            return {"type": "stylist_off", "label": f"{name} is off this day"}
        day = DAY_ORDER[d.weekday()]
        working_days = normalize_working_days(staff_row.get("working_days"))
        if working_days and day not in working_days:
            return {"type": "stylist_off", "label": f"{name} doesn't work {DAY_LABELS[day]}"}
        hours = normalize_working_hours(staff_row.get("working_hours")).get(day)
        if hours and time_str:
            t = _to_minutes(time_str)
            start, end = _to_minutes(hours["start"]), _to_minutes(hours["end"])
            if t is not None and start is not None and end is not None and not (start <= t < end):
                return {"type": "stylist_off", "label": f"{name} not in at this time"}
    return None
