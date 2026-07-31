"""Sample data for a card-free demo tenant.

A prospect who hasn't paid yet lands on an empty dashboard, which shows them
nothing about what the product does. This fills that dashboard with three weeks
of plausible salon history so they can see the calls, calendar, messages and
analytics working before they commit a card.

Two rules govern everything in here:

1. **Nothing seeded may ever reach a real caller.** A demo tenant has no Twilio
   number, so no call can route to it. On activation the whole lot is purged and
   the config is reset (see database.db_tenant_deactivate_demo) — a prospect must
   never go live with "Short Cut $28" still in their service list.
2. **Every phone number is fictional.** All sample numbers sit in the reserved
   555-01XX range so a curious prospect clicking "call back" can never dial a
   real stranger.

The data is generated from a client_id-seeded RNG, so a given demo tenant looks
the same on every read, but two prospects don't see identical dashboards.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import config_service
import database

logger = logging.getLogger("nuvatra")

# How much history a demo dashboard shows. Three weeks is enough for the
# analytics week-over-week views to have something to say.
DEMO_HISTORY_DAYS = 21

# 555-0100..555-0199 is reserved for fiction — safe to display and safe to dial.
_AREA = "415"


def _fake_phone(n: int) -> str:
    """A fictional US number in the reserved 555-0100..555-0199 block. n is 100..199."""
    if not 100 <= n <= 199:
        raise ValueError(f"demo phone {n} outside the reserved 555-01XX fiction block")
    return f"+1{_AREA}555{n:04d}"


# The sample shop's own line — what callers dialed, and the demo forwarding number.
_DEMO_SHOP_PHONE = _fake_phone(100)


SAMPLE_SERVICES = [
    {"id": "svc-haircut", "name": "Haircut", "price": 28, "duration_minutes": 30},
    {"id": "svc-kids", "name": "Kids Cut", "price": 20, "duration_minutes": 30},
    {"id": "svc-buzz", "name": "Buzz Cut", "price": 18, "duration_minutes": 20},
    {"id": "svc-beard", "name": "Beard Trim", "price": 15, "duration_minutes": 15},
    {"id": "svc-style", "name": "Shampoo & Style", "price": 35, "duration_minutes": 30},
    {"id": "svc-color", "name": "Color", "price": 75, "duration_minutes": 60},
]

SAMPLE_STAFF = [
    {
        "id": "stf-maya",
        "name": "Maya",
        "role": "Senior Stylist",
        "phone": "",
        "description": "Cuts, color and styling",
        "service_ids": ["svc-haircut", "svc-style", "svc-color"],
    },
    {
        "id": "stf-devon",
        "name": "Devon",
        "role": "Barber",
        "phone": "",
        "description": "Cuts, buzz cuts and beard work",
        "service_ids": ["svc-haircut", "svc-buzz", "svc-beard"],
    },
    {
        "id": "stf-priya",
        "name": "Priya",
        "role": "Stylist",
        "phone": "",
        "description": "Cuts, kids cuts and styling",
        "service_ids": ["svc-haircut", "svc-kids", "svc-style"],
    },
]

_CUSTOMERS = [
    ("Jordan Ellis", 101), ("Sam Nguyen", 102), ("Taylor Brooks", 103),
    ("Chris Alvarez", 104), ("Morgan Lee", 105), ("Riley Chen", 106),
    ("Casey Donovan", 107), ("Avery Patel", 108), ("Jamie Okafor", 109),
    ("Drew Sullivan", 110), ("Quinn Barrett", 111), ("Reese Kowalski", 112),
    ("Skyler Moreno", 113), ("Rowan Fitzgerald", 114), ("Elliot Vasquez", 115),
]

# (service_id, reason label) — what the caller actually asked for.
_REASONS = [
    ("svc-haircut", "Haircut"),
    ("svc-haircut", "Haircut"),
    ("svc-buzz", "Buzz Cut"),
    ("svc-beard", "Beard Trim"),
    ("svc-kids", "Kids Cut"),
    ("svc-style", "Shampoo & Style"),
    ("svc-color", "Color"),
]

_BOOKED_SUMMARIES = [
    "Booked {name} for a {service} with {staff} on {date} at {time}. Confirmation text sent.",
    "{name} called to book a {service}. Offered the first opening with {staff}; booked {date} at {time}.",
    "New booking: {service} for {name}, {date} at {time} with {staff}. Caller asked about parking — gave the lot directions.",
    "{name} rebooked their usual {service} with {staff} for {date} at {time}.",
]

_NO_BOOKING_SUMMARIES = [
    "Caller asked for a {service} on a day we're fully booked. Offered the next two openings; they said they'd call back.",
    "Price check on {service}. Quoted the current rate — no booking made.",
    "Caller wanted a walk-in slot today. Explained the wait and offered to book instead; they declined.",
]

_FORWARDED_SUMMARIES = [
    "Caller asked to speak to a manager about a previous visit. Transferred to the shop.",
    "Caller had a question the receptionist couldn't answer. Transferred to the shop.",
]

_MESSAGES = [
    ("Jordan Ellis", 101, "Running about 10 minutes late for my 2:30 — please let Maya know.", "normal"),
    ("Morgan Lee", 105, "Need to move my Saturday color appointment to the following week if possible.", "normal"),
    ("Casey Donovan", 107, "Left my sunglasses at the front desk yesterday — can someone check?", "low"),
    ("Drew Sullivan", 110, "Wedding on the 14th, need three cuts back to back that morning. Can you fit us in?", "high"),
]

_LEADS = [
    ("Skyler Moreno", 113, "Asked about color pricing — wants a callback"),
    ("Rowan Fitzgerald", 114, "New to the area, looking for a regular barber"),
    ("Elliot Vasquez", 115, "Wanted a Saturday slot we didn't have — worth a follow-up"),
]

# Two-way SMS threads, stored the way handle_incoming_sms writes them: newest last,
# role "user" = the customer, "assistant" = the receptionist.
_SMS_THREADS = [
    ("Jordan Ellis", 101, [
        {"role": "assistant", "content": "Hi Jordan — you're booked for a Haircut on Thursday at 2:30 PM with Maya. Reply YES to confirm."},
        {"role": "user", "content": "yes"},
        {"role": "assistant", "content": "All set. See you Thursday at 2:30!"},
    ]),
    ("Morgan Lee", 105, [
        {"role": "assistant", "content": "Hi Morgan — confirming your Color appointment Saturday at 11:00 AM with Maya. Reply YES to confirm."},
        {"role": "user", "content": "Can I move it to the following Saturday instead?"},
        {"role": "assistant", "content": "Of course — I've passed that to the salon and they'll confirm the new time shortly."},
    ]),
    ("Casey Donovan", 107, [
        {"role": "assistant", "content": "Hi Casey — you're booked for a Beard Trim tomorrow at 4:00 PM with Devon. Reply YES to confirm."},
        {"role": "user", "content": "yes thanks"},
        {"role": "assistant", "content": "Confirmed. See you tomorrow at 4."},
    ]),
    ("Avery Patel", 108, [
        {"role": "user", "content": "Are you open on Sunday?"},
        {"role": "assistant", "content": "We are — Sundays 10 AM to 4 PM. Would you like me to book something?"},
        {"role": "user", "content": "Not yet, just checking. Thanks!"},
    ]),
]


def demo_config(client_id: str, business_name: str, plan: str = "pro") -> dict:
    """Business config for a demo tenant: the prospect's own name on a fully
    populated sample shop, so the dashboard reads as theirs at a glance."""
    cfg = config_service._default_client_config_data(client_id, plan)
    cfg["business_name"] = business_name
    cfg["name"] = business_name
    cfg["hours"] = "Monday–Friday: 9 AM – 7 PM, Saturday: 9 AM – 5 PM, Sunday: 10 AM – 4 PM"
    cfg["address"] = "1200 Market St, San Francisco, CA"
    cfg["email"] = "hello@example.com"
    cfg["receptionist_name"] = "Riley"
    cfg["forwarding_phone"] = _DEMO_SHOP_PHONE
    cfg["services"] = [dict(s) for s in SAMPLE_SERVICES]
    cfg["staff"] = [dict(s) for s in SAMPLE_STAFF]
    cfg["departments"] = ["Appointments", "General", "Other"]
    cfg["greeting"] = f"Thanks for calling {business_name}. How can I help you today?"
    cfg["specials"] = [
        {
            "id": "spc-weekday",
            "title": "Weekday Special",
            "description": "$5 off any cut, Monday–Thursday before 2 PM.",
            "valid_until": "",
        }
    ]
    # Marks this config as sample data. The UI reads the tenant's demo_mode flag,
    # not this — it's here so a config dump is self-describing.
    cfg["is_demo_data"] = True
    return cfg


def _business_hour_utc(rng: random.Random) -> int:
    """An hour-of-day (UTC) shaped like a real shop's call volume: a late-morning
    bump, a lunch lull, an after-work peak. Analytics buckets by UTC hour, so the
    peak-times chart shows this curve directly."""
    hours = [15, 16, 17, 18, 19, 20, 21, 22, 23]
    weights = [4, 7, 9, 6, 5, 6, 9, 8, 4]
    return rng.choices(hours, weights=weights, k=1)[0]


def _hhmm(minutes_from_midnight: int) -> str:
    h, m = divmod(minutes_from_midnight, 60)
    return f"{h:02d}:{m:02d}"


def seed_demo_tenant(
    client_id: str,
    business_name: str,
    *,
    plan: str = "pro",
    now: Optional[datetime] = None,
) -> dict:
    """Fill a demo tenant with sample config + history. Returns a count summary.

    Assumes the tenant row already exists and is flagged demo_mode. Safe to call
    only on a tenant with no real data — everything written here is purged on
    activation.
    """
    cid = (client_id or "").strip()
    if not cid:
        raise ValueError("client_id required")
    now = now or datetime.now(timezone.utc)
    rng = random.Random(f"demo:{cid}")

    # Several database helpers scope writes by the request contextvar rather than
    # an argument (db_call_log_append, db_booked_slot_reserve, db_caller_memory_upsert),
    # so the context must be pinned before any of them run or the rows land on
    # whatever client_id happens to be ambient — 'default' in the worst case.
    database.set_request_client_id(cid)

    config_service.save_raw_client_config(cid, demo_config(cid, business_name, plan))

    counts = {"calls": 0, "appointments": 0, "messages": 0, "leads": 0, "texts": 0}
    services_by_id = {s["id"]: s for s in SAMPLE_SERVICES}
    staff_for_service: dict[str, list[dict]] = {
        s["id"]: [st for st in SAMPLE_STAFF if s["id"] in st["service_ids"]] for s in SAMPLE_SERVICES
    }
    total_voice_seconds = 0
    sms_sent = 0

    for day_offset in range(DEMO_HISTORY_DAYS, -1, -1):
        day = now - timedelta(days=day_offset)
        # Sunday is quiet; Friday/Saturday are busy.
        weekday = day.weekday()
        base_calls = {5: 5, 4: 4, 6: 1}.get(weekday, 3)
        for _ in range(rng.randint(max(1, base_calls - 1), base_calls + 2)):
            cust_name, cust_n = rng.choice(_CUSTOMERS)
            cust_phone = _fake_phone(cust_n)
            service_id, service_label = rng.choice(_REASONS)
            service = services_by_id[service_id]
            candidates = staff_for_service.get(service_id) or SAMPLE_STAFF
            staff = rng.choice(candidates)

            start = day.replace(
                hour=_business_hour_utc(rng),
                minute=rng.randint(0, 59),
                second=0,
                microsecond=0,
            )
            roll = rng.random()
            if roll < 0.62:
                outcome, booked = "answered_by_ai", True
                duration = rng.randint(70, 190)
            elif roll < 0.84:
                outcome, booked = "no_booking", False
                duration = rng.randint(35, 95)
            elif roll < 0.95:
                outcome, booked = "forwarded", False
                duration = rng.randint(20, 60)
            else:
                outcome, booked = "missed", False
                duration = rng.randint(5, 18)

            appointment_id = None
            apt_date = ""
            apt_time = ""
            if booked:
                # Book 0–10 days after the call, during opening hours.
                apt_day = day + timedelta(days=rng.randint(0, 10))
                apt_date = apt_day.strftime("%Y-%m-%d")
                apt_time = _hhmm(rng.randrange(9 * 60, 18 * 60, 30))
                past = apt_day < now
                if past:
                    status = "completed"
                else:
                    status = rng.choice(["confirmed", "confirmed", "accepted", "pending_customer"])
                try:
                    apt = database.db_appointments_insert(
                        {
                            "client_id": cid,
                            "name": cust_name,
                            "email": "",
                            "phone": cust_phone,
                            "date": apt_date,
                            "time": apt_time,
                            "reason": service_label,
                            "status": status,
                            "source": "receptionist",
                            "staff_id": staff["id"],
                        }
                    )
                    appointment_id = apt.get("id")
                    counts["appointments"] += 1
                    sms_sent += 1  # every AI booking sends a confirmation text
                except Exception as e:
                    logger.warning("demo_seed appointment insert failed cid=%s: %s", cid, e)

                if appointment_id and not past:
                    # Only future appointments hold a calendar slot; a taken slot in
                    # the past would block nothing and just clutter availability.
                    try:
                        database.db_booked_slot_reserve(
                            apt_date,
                            apt_time,
                            appointment_id,
                            service["duration_minutes"],
                            staff["id"],
                        )
                    except Exception as e:
                        logger.warning("demo_seed slot reserve failed cid=%s: %s", cid, e)

            if booked:
                summary = rng.choice(_BOOKED_SUMMARIES).format(
                    name=cust_name, service=service_label, staff=staff["name"],
                    date=apt_date, time=apt_time,
                )
            elif outcome == "no_booking":
                summary = rng.choice(_NO_BOOKING_SUMMARIES).format(service=service_label)
            elif outcome == "forwarded":
                summary = rng.choice(_FORWARDED_SUMMARIES)
            else:
                summary = ""  # a missed call has nothing to summarize

            try:
                database.db_call_log_append(
                    {
                        "call_sid": f"CAdemo{rng.getrandbits(64):016x}",
                        "from_number": cust_phone,
                        "to_number": _DEMO_SHOP_PHONE,
                        "start_iso": start.isoformat(),
                        "end_iso": (start + timedelta(seconds=duration)).isoformat(),
                        "outcome": outcome,
                        "duration_sec": duration,
                        "category": None,
                        "call_summary": summary or None,
                    }
                )
                counts["calls"] += 1
                total_voice_seconds += duration
            except Exception as e:
                logger.warning("demo_seed call_log append failed cid=%s: %s", cid, e)

            try:
                database.db_caller_memory_upsert(
                    cust_phone, name=cust_name, last_reason=service_label, increment_count=True
                )
            except Exception as e:
                logger.warning("demo_seed caller_memory failed cid=%s: %s", cid, e)

    for name, n, body, urgency in _MESSAGES:
        try:
            database.db_messages_insert(
                {
                    "caller_name": name,
                    "caller_phone": _fake_phone(n),
                    "message": body,
                    "urgency": urgency,
                    "status": "unread" if urgency != "low" else "read",
                },
                client_id=cid,
            )
            counts["messages"] += 1
        except Exception as e:
            logger.warning("demo_seed message insert failed cid=%s: %s", cid, e)

    for name, n, reason in _LEADS:
        try:
            if database.db_leads_insert(cid, name, _fake_phone(n), reason, "call"):
                counts["leads"] += 1
        except Exception as e:
            logger.warning("demo_seed lead insert failed cid=%s: %s", cid, e)

    # SMS threads. Without these the dashboard's "Texts Exchanged" card reads 0 while
    # the usage meter shows dozens of texts sent — which makes the demo look broken.
    for _cust_name, cust_n, thread in _SMS_THREADS:
        try:
            database.db_sms_session_upsert(_fake_phone(cust_n), cid, thread)
            counts["texts"] += len(thread)
        except Exception as e:
            logger.warning("demo_seed sms thread failed cid=%s: %s", cid, e)

    # Usage meters, so the plan/usage widget isn't sitting at zero.
    month = now.strftime("%Y-%m")
    try:
        database.db_usage_increment_voice(cid, month, max(1, round(total_voice_seconds / 60)))
        for _ in range(sms_sent):
            database.db_usage_increment_sms(cid, month)
    except Exception as e:
        logger.warning("demo_seed usage seed failed cid=%s: %s", cid, e)

    logger.info("demo_seed_complete cid=%s counts=%s", cid, counts)
    return counts
