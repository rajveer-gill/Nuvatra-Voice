"""Import appointments pasted out of an external booking system (e.g. Zenoti).

Zenoti refused API access (they sell a competing AI receptionist), so the practical
bridge is the one their own UI already allows: a salon manager selects their day in
the Zenoti **Queue view** (the Visit view blocks selection), copies it, and pastes it
here. One paste carries the whole queue.

The pasted text is messy and semi-structured, and its exact shape varies by view and
by Zenoti release, so extraction is done by the LLM rather than a regex — a regex
would break the first time a column moved. But the model is only trusted to *read*;
every field it returns is re-validated and normalized here, because a hallucinated
date must never reach the calendar.

A paste is a SNAPSHOT, stale the moment it is taken. Callers must treat imported rows
as context ("what was booked as of 9:14am"), never as live availability.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date as _date
from datetime import datetime, timedelta
from typing import Optional

import llm_provider

logger = logging.getLogger("nuvatra")

# Reuse the receptionist brain's model by default — one env var to roll back or A/B.
IMPORT_LLM_MODEL = (os.getenv("IMPORT_LLM_MODEL") or os.getenv("VOICE_LLM_MODEL") or "gpt-4o-mini").strip()

# Guardrails on a single paste. A day's queue for one salon is tens of rows; anything
# far beyond that is a paste of the wrong thing (or an attempt to run up token cost).
MAX_PASTE_CHARS = 20000
MAX_ROWS = 200

_EXTRACT_SYSTEM = """You extract appointments from text copied out of a salon booking system (usually Zenoti's queue view).

Return ONLY a JSON object, no prose, no markdown fence:
{"appointments": [{"customer_name": str, "service": str, "stylist": str, "time": str, "date": str, "is_request": bool, "price": str, "notes": str}]}

Zenoti's queue view pastes as one value per line, repeating this block per guest:
  <queue number>        e.g. 10
  <guest name>          e.g. Jannie B
  <service>|            e.g. All-over color (+1)|     <- trailing pipe, (+N) = N add-ons
  <stylist>             e.g. Tina (Req.)   or   First Available
  <arrived time>        e.g. 12:00 pm
  <original time>       e.g. 12:00 pm      <- THIS is the booked appointment time
  <expected time>       e.g. 12:00 pm
  Total : $138.00
Column headers appear once at the top: Guest, Service, Arrived, Original, Expected.

Rules:
- time: 24-hour "HH:MM". Three times appear per guest — arrived, ORIGINAL, expected. Use the ORIGINAL (middle) one: that's the booked slot. Never invent a time.
- date: "YYYY-MM-DD" only if the text actually states one. A queue view is a single day and usually shows NO date — return "" then. Do NOT guess today's date.
- stylist: the staff name with any "(Req.)" / "(Request)" marker REMOVED — "Tina (Req.)" -> "Tina". If it says "First Available", "Any", or similar, use "" (empty).
- is_request: true when the stylist was marked as requested (e.g. "(Req.)"); false for first-available.
- service: the service name, WITHOUT the trailing "|". Keep it exactly as written otherwise — do not translate, expand, or normalize it.
- price: the "Total : $138.00" amount as a plain number string like "138.00". "" if absent.
- customer_name: the guest's name only — never the queue number, phone, or ID.
- notes: anything else worth keeping, e.g. "1 add-on" when the service showed (+1). "" if nothing.
- SKIP these entirely: column headers, the leading queue number, "Please add guest basic details", "Add Email", blank lines.
- If the text contains no appointments at all, return {"appointments": []}.
Extract exactly what is written. Accuracy matters far more than filling every field."""


def _extract_json_object(text: str) -> Optional[dict]:
    """Pull the JSON object out of a model reply, tolerating a code fence or stray prose."""
    s = (text or "").strip()
    if not s:
        return None
    # Strip a ```json ... ``` fence if present.
    fence = re.search(r"```(?:json)?\s*(.+?)```", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # Last resort: the outermost {...} span.
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(s[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def _normalize_time(raw) -> str:
    """Coerce a model-supplied time to HH:MM, or "" if it isn't a real time.

    Accepts "14:00", "2:00 PM", "2 PM", "0900". Rejects anything out of range rather
    than clamping, so a garbage value drops the row instead of booking a wrong hour.
    """
    s = str(raw or "").strip().upper().replace(".", "")
    if not s:
        return ""
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", s)
    if not m:
        m2 = re.match(r"^(\d{2})(\d{2})$", s)  # 0900
        if not m2:
            return ""
        h, mi, ampm = int(m2.group(1)), int(m2.group(2)), None
    else:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        ampm = m.group(3)
    if ampm == "PM" and h != 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return ""
    return f"{h:02d}:{mi:02d}"


def _normalize_date(raw, *, fallback: Optional[str] = None) -> str:
    """Coerce to YYYY-MM-DD. Falls back to the caller-supplied date (the day the paste
    is for) when the text carried no date — common, since a queue view is one day and
    often shows no date at all."""
    s = str(raw or "").strip()
    if not s:
        return fallback or ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d %Y", "%B %d %Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    # Bare "7/22" style — assume the fallback's year.
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})$", s)
    if m and fallback:
        try:
            year = datetime.strptime(fallback, "%Y-%m-%d").year
            return _date(year, int(m.group(1)), int(m.group(2))).isoformat()
        except Exception:
            pass
    return fallback or ""


_FIRST_AVAILABLE = {"first available", "first avail", "any", "anyone", "any stylist", "n/a", "-"}

# Zenoti marks a requested stylist as "Tina (Req.)". Strip the marker from the name —
# whether the guest requested them is carried separately, in is_request.
_REQ_MARKER = re.compile(r"\s*\((?:req\.?|request(?:ed)?)\)\s*$", re.IGNORECASE)


def _clean_stylist(raw) -> tuple[str, bool]:
    """Return (stylist_name, was_requested). Empty name means first-available."""
    s = re.sub(r"\s+", " ", str(raw or "").strip())
    requested = bool(_REQ_MARKER.search(s))
    s = _REQ_MARKER.sub("", s).strip()
    if s.lower() in _FIRST_AVAILABLE:
        return "", False
    return s[:120], requested


def _clean_service(raw) -> tuple[str, str]:
    """Return (service_name, note). Zenoti appends a trailing '|' and marks add-ons
    as '(+1)'; the count is worth keeping but doesn't belong in the service name."""
    s = re.sub(r"\s+", " ", str(raw or "").strip()).rstrip("|").strip()
    note = ""
    m = re.search(r"\(\+(\d+)\)\s*$", s)
    if m:
        n = int(m.group(1))
        note = f"{n} add-on" + ("s" if n != 1 else "")
        s = s[: m.start()].strip()
    return s[:200], note


def _clean_price(raw) -> str:
    """Normalize '$138.00' / 'Total : $138.00' / '138' to '138.00'. '' if not a price."""
    digits = re.search(r"(\d+(?:\.\d{1,2})?)", str(raw or "").replace(",", ""))
    if not digits:
        return ""
    try:
        return f"{float(digits.group(1)):.2f}"
    except ValueError:
        return ""


def parse_pasted_appointments(
    text: str,
    *,
    default_date: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Extract appointments from pasted text.

    Returns {"appointments": [...], "warnings": [...]}. Never raises for bad model
    output or unparseable text — it returns an empty list with a warning, so the UI can
    say "couldn't read that" instead of 500ing.

    default_date is the day the paste covers (the queue view usually omits the date).
    """
    warnings: list[str] = []
    raw = (text or "").strip()
    if not raw:
        return {"appointments": [], "warnings": ["Nothing was pasted."]}
    if len(raw) > MAX_PASTE_CHARS:
        raw = raw[:MAX_PASTE_CHARS]
        warnings.append(
            f"Only the first {MAX_PASTE_CHARS:,} characters were read — paste one day at a time."
        )
    fallback_date = _normalize_date(default_date) or datetime.now().date().isoformat()

    try:
        reply = llm_provider.chat(
            model=(model or IMPORT_LLM_MODEL),
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": raw},
            ],
            max_tokens=4000,
            temperature=0,  # extraction, not creativity
        )
    except Exception as e:
        logger.error("appointment_import_llm_failed err=%s", e)
        return {
            "appointments": [],
            "warnings": ["Could not analyze the pasted text. Please try again."],
        }

    obj = _extract_json_object(reply)
    if not obj or not isinstance(obj.get("appointments"), list):
        logger.warning("appointment_import_unparseable reply_prefix=%r", (reply or "")[:200])
        return {
            "appointments": [],
            "warnings": [
                "Couldn't find appointments in that text. Try copying from the Queue view."
            ],
        }

    rows = obj["appointments"][:MAX_ROWS]
    if len(obj["appointments"]) > MAX_ROWS:
        warnings.append(f"Only the first {MAX_ROWS} appointments were kept.")

    out: list[dict] = []
    skipped = 0
    for r in rows:
        if not isinstance(r, dict):
            skipped += 1
            continue
        name = re.sub(r"\s+", " ", str(r.get("customer_name") or "").strip())[:200]
        time = _normalize_time(r.get("time"))
        # A row with no name or no usable time isn't an appointment we can act on.
        if not name or not time:
            skipped += 1
            continue
        stylist, requested = _clean_stylist(r.get("stylist"))
        service, addon_note = _clean_service(r.get("service"))
        notes = str(r.get("notes") or "").strip()[:500]
        if addon_note and addon_note.lower() not in notes.lower():
            notes = f"{addon_note} · {notes}" if notes else addon_note
        out.append(
            {
                "customer_name": name,
                "service": service,
                "stylist": stylist,
                "date": _normalize_date(r.get("date"), fallback=fallback_date),
                "time": time,
                # Trust the marker in the text over the model's own judgement.
                "is_request": requested or bool(r.get("is_request")),
                "price": _clean_price(r.get("price")),
                "notes": notes,
            }
        )
    if skipped:
        warnings.append(f"{skipped} row(s) were skipped — missing a name or a readable time.")
    return {"appointments": out, "warnings": warnings}


def import_key(row: dict) -> str:
    """Stable identity for a pasted appointment, so re-pasting the same queue updates
    instead of duplicating. Deliberately date+time+name: the same guest at the same
    slot is the same appointment, whatever else changed about it."""
    name = re.sub(r"[^a-z0-9]", "", (row.get("customer_name") or "").lower())
    return f"{(row.get('date') or '').strip()}|{(row.get('time') or '').strip()}|{name}"
