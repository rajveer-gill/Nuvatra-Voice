"""Per-stylist working-day / working-hour helpers.

A staff record may carry:
- working_days: list of lowercase day codes (mon..sun) the person works. Empty = no
  constraint (works whenever the shop is open).
- working_hours: optional {day_code: {"start": "HH:MM", "end": "HH:MM"}} narrowing the
  hours on specific days. A day with no entry = full shop hours that day.

These are used both for the voice prompt (so the AI knows) and as a server-side
booking backstop (reject a booking for a stylist on a day/time they don't work).
"""

from __future__ import annotations

from datetime import date as _date
from typing import Optional

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


def weekday_code(date_str: str) -> Optional[str]:
    try:
        return DAY_ORDER[_date.fromisoformat(str(date_str).strip()).weekday()]
    except (ValueError, AttributeError):
        return None


def working_days_prompt_text(staff_row: dict) -> str:
    """Prompt fragment like 'Monday, Tuesday, Friday (Friday 12:00 PM–5:00 PM)'. Empty when no schedule."""
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


def staff_unavailable_message(
    staff_row: dict, date_str: str, time_str: str = ""
) -> Optional[str]:
    """If the stylist doesn't work the given day (or time), return a caller-facing reason; else None."""
    name = (staff_row.get("name") or "").strip() or "That stylist"
    day = weekday_code(date_str)
    if not day:
        return None
    working_days = normalize_working_days(staff_row.get("working_days"))
    if working_days and day not in working_days:
        worked = ", ".join(DAY_LABELS[d] for d in working_days)
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
