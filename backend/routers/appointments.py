"""Appointments API — full domain: CRUD, accept, and AI-polished decline/cancel.

All nine appointment routes live here. Slot/duration/calendar logic comes from
booking_service; the decline/cancel routes use booking_service.polish_owner_*_sms
(which calls runtime.client). Helpers are resolved by module (deps/database/
booking_service/config_service/sms_service/runtime) so monkeypatches target owners.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import booking_service
import config_service
import database
import deps
import runtime
import sms_service
from observability import system_info

router = APIRouter()


class AppointmentRequest(BaseModel):
    name: str
    email: str = ""
    phone: str
    date: str
    time: str
    reason: str
    source: Optional[str] = "manual"  # "receptionist" | "manual"
    staff_id: Optional[str] = None  # stylist UUID from Settings staff list


# ---------- Import from an external booking system (paste-in) ----------


class ImportPreviewRequest(BaseModel):
    # Raw text copied out of the external system's queue/day view.
    text: str = Field(..., max_length=40000)
    # The day the paste covers; queue views usually omit the date.
    date: Optional[str] = None


class ImportedAppointment(BaseModel):
    customer_name: str
    service: str = ""
    stylist: str = ""
    date: str
    time: str
    is_request: bool = False
    price: str = ""
    notes: str = ""


class ImportCommitRequest(BaseModel):
    appointments: list[ImportedAppointment] = Field(default_factory=list)


def _require_external_booking(tenant: Optional[dict]) -> str:
    """Import only makes sense when someone else owns the calendar. For an internal
    store, pasting appointments in would create rows that compete with the real
    booking flow, so it's refused rather than quietly allowed."""
    cid = deps._bind_tenant_db_context(tenant)
    if not config_service.is_external_booking():
        raise HTTPException(
            status_code=400,
            detail="Appointment import is only available for stores whose calendar lives in another system.",
        )
    return cid


def _staff_id_by_name(name: str, staff: list) -> Optional[str]:
    """Match a pasted stylist name to someone on the roster.

    The other system writes names as its operators typed them — "BRENDA TO",
    "Dai Dao", "RIN CHAN" — so matching is case- and space-insensitive, and a first
    name alone counts when it is unambiguous ("Tina" for "Tina Nguyen"). Anything
    ambiguous or unrecognised returns None and the appointment lands unassigned,
    which is honest: guessing would put a customer in front of the wrong stylist.
    """
    want = re.sub(r"\s+", " ", (name or "").strip().lower())
    if not want:
        return None
    rows = [
        (str(m.get("id") or ""), re.sub(r"\s+", " ", str(m.get("name") or "").strip().lower()))
        for m in (staff or [])
        if m.get("id") and str(m.get("name") or "").strip()
    ]
    for sid, full in rows:
        if full == want:
            return sid
    # First name only, and only when exactly one person answers to it.
    firsts = [(sid, full) for sid, full in rows if full.split(" ")[0] == want]
    if len(firsts) == 1:
        return firsts[0][0]
    return None


@router.post("/api/appointments/import/preview")
def import_appointments_preview(
    req: ImportPreviewRequest,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Analyze pasted text and return what we found. Writes NOTHING.

    The preview exists so a misread time is caught by a human before it reaches the
    calendar — the paste is parsed by an LLM, and this is the checkpoint on that.
    Rows already imported are flagged so re-pasting a day is obvious and safe.
    """
    import appointment_import

    cid = _require_external_booking(tenant)
    result = appointment_import.parse_pasted_appointments(req.text, default_date=req.date)
    rows = result.get("appointments") or []
    existing = {
        appointment_import.import_key(
            {"date": a.get("date"), "time": a.get("time"), "customer_name": a.get("name")}
        )
        for a in (database.db_appointments_get_all(client_id=cid) if runtime.USE_DB else [])
    }
    # Which stylists on this paste don't exist on the roster. Surfaced BEFORE import,
    # because that's when it can still be fixed — afterwards those appointments are
    # silently unassigned and the day reads as if nobody is working.
    roster = (config_service.get_business_info() or {}).get("staff") or []
    unmatched: dict = {}
    new_count = 0
    for r in rows:
        r["already_imported"] = appointment_import.import_key(r) in existing
        if not r["already_imported"]:
            new_count += 1
        who = (r.get("stylist") or "").strip()
        if who and not _staff_id_by_name(who, roster):
            unmatched.setdefault(who.lower(), who)
    system_info(
        "appointment_import_preview",
        client_id=cid,
        found=len(rows),
        new=new_count,
        chars=len(req.text or ""),
    )
    return {
        "appointments": rows,
        "warnings": result.get("warnings") or [],
        "found": len(rows),
        "new": new_count,
        "already_imported": len(rows) - new_count,
        "unmatched_stylists": sorted(unmatched.values(), key=str.lower),
        # Stamp so the UI can show "as of ..." — a paste is a snapshot, never live.
        "analyzed_at": datetime.now().isoformat(),
    }


@router.post("/api/appointments/import/commit")
def import_appointments_commit(
    req: ImportCommitRequest,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Persist reviewed rows from a preview.

    Imported rows are recorded as already-confirmed appointments (they exist in the
    other system — that's the source of truth), and no calendar slot is reserved here.
    Idempotent on date+time+name, so re-pasting the same day updates rather than
    duplicating.
    """
    import appointment_import

    cid = _require_external_booking(tenant)
    if not runtime.USE_DB:
        raise HTTPException(status_code=503, detail="Database required")
    existing = {}
    for a in database.db_appointments_get_all(client_id=cid):
        key = appointment_import.import_key(
            {"date": a.get("date"), "time": a.get("time"), "customer_name": a.get("name")}
        )
        existing[key] = a
    roster = (config_service.get_business_info() or {}).get("staff") or []
    created, updated, skipped, invalid = 0, 0, 0, 0
    unmatched: set = set()
    for row in req.appointments:
        data = row.model_dump()
        # Re-validate here, not just in preview: these rows are hand-editable in the UI
        # and this endpoint accepts arbitrary client JSON, so a bad date/time must never
        # reach the calendar on the strength of the client having sent it.
        data["time"] = appointment_import._normalize_time(data.get("time"))
        data["date"] = appointment_import._normalize_date(data.get("date"))
        data["customer_name"] = (data.get("customer_name") or "").strip()[:200]
        if not (data["time"] and data["date"] and data["customer_name"]):
            invalid += 1
            continue
        key = appointment_import.import_key(data)
        # Service, stylist, price and notes have no columns of their own, so they're
        # folded into `reason` — the field the dashboard already displays.
        stylist_name = (data.get("stylist") or "").strip()
        # Link to the roster so the day can be read one column per stylist. The name
        # still goes into `reason` as well, so it survives even when nobody matches.
        staff_id = _staff_id_by_name(stylist_name, roster)
        if stylist_name and not staff_id:
            unmatched.add(stylist_name[:80])
        stylist = stylist_name
        if stylist:
            stylist = f"with {stylist}" + (" (requested)" if data.get("is_request") else "")
        price = (data.get("price") or "").strip()
        reason_bits = [
            b for b in (
                data.get("service"),
                stylist,
                f"${price}" if price else "",
                data.get("notes"),
            ) if b
        ]
        reason = " — ".join(reason_bits) or "Imported appointment"
        if key in existing:
            prior = existing[key]
            try:
                database.db_appointments_update(
                    prior["id"], client_id=cid, reason=reason, status="confirmed",
                    staff_id=staff_id,
                )
                updated += 1
            except Exception as e:
                system_info("appointment_import_update_failed", apt_id=prior.get("id"), error=str(e))
                skipped += 1
            continue
        try:
            database.db_appointments_insert(
                {
                    "client_id": cid,
                    "name": data["customer_name"],
                    "email": "",
                    "phone": "",
                    "date": data["date"],
                    "time": data["time"],
                    "reason": reason,
                    # Already booked in the other system — not awaiting anyone here.
                    "status": "confirmed",
                    "source": "imported",
                    "staff_id": staff_id,
                }
            )
            created += 1
        except Exception:
            skipped += 1
    system_info(
        "appointment_import_commit",
        client_id=cid,
        created=created,
        updated=updated,
        skipped=skipped,
        invalid=invalid,
    )
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "invalid": invalid,
        # Named so the UI can offer to add them — an unmatched stylist means that day
        # reads as "Unassigned" instead of showing who is actually busy.
        "unmatched_stylists": sorted(unmatched),
    }


class AppointmentUpdate(BaseModel):
    status: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    reason: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


@router.post("/api/appointments")
def create_appointment(
    appointment: AppointmentRequest,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    cid = deps._bind_tenant_db_context(tenant)
    try:
        source = (appointment.source or "manual").strip().lower()
        if source not in ("receptionist", "manual"):
            source = "manual"
        status = "pending_review" if source == "receptionist" else "pending"
        date = (appointment.date or "").strip()
        time = (appointment.time or "").strip()
        staff_key = booking_service._optional_staff_id_validated(appointment.staff_id)
        duration_min = booking_service._appointment_duration_minutes(
            {"reason": appointment.reason or ""}
        )
        if date and time:
            if not booking_service.is_slot_available(
                date, time, duration_min, staff_key
            ):
                raise HTTPException(
                    status_code=409, detail="That time slot is already booked."
                )
        appointment_data = {
            "name": appointment.name,
            "email": appointment.email or "",
            "phone": appointment.phone or "",
            "date": date,
            "time": time,
            "reason": appointment.reason or "",
            "source": source,
            "status": status,
            "staff_id": staff_key,
            "client_id": cid,
        }
        if runtime.USE_DB:
            row = database.db_appointments_insert(appointment_data)
            appointment_id = row["id"]
        else:
            appointment_id = len(runtime.appointments) + 1
            appointment_data["id"] = appointment_id
            appointment_data["created_at"] = datetime.now().isoformat()
            runtime.appointments.append(appointment_data)
        if date and time:
            if not booking_service.reserve_slot(
                date, time, appointment_id, duration_min, staff_key
            ):
                # A concurrent booking claimed the slot between the availability check
                # and the reserve. Cancel the row we just created and report the conflict.
                if runtime.USE_DB:
                    database.db_appointments_update(
                        appointment_id, status="cancelled", client_id=cid
                    )
                raise HTTPException(
                    status_code=409, detail="That time slot was just booked. Please pick another time."
                )
        appointment_data["id"] = appointment_id
        appointment_data.setdefault("created_at", datetime.now().isoformat())
        return {"success": True, "appointment": appointment_data}
    except HTTPException:
        raise
    except Exception as e:
        raise deps._server_error("create appointment failed", e)


@router.get("/api/appointments")
def get_appointments(
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    cid = deps._bind_tenant_db_context(tenant)
    orphans_removed = booking_service._reconcile_booked_slots_orphans() if runtime.USE_DB else 0
    lst = database.db_appointments_get_all(client_id=cid) if runtime.USE_DB else runtime.appointments
    # Tag appointments that fall on a shop closure or the stylist's time-off / off day so the
    # dashboard can highlight them. Build the lookup once (O(staff)), then O(1) per appointment.
    import staff_schedule

    _biz = config_service.get_business_info()
    _closures = _biz.get("closures") or []
    _staff_by_id = {
        str(s.get("id")): s for s in (_biz.get("staff") or []) if s.get("id")
    }
    for a in lst:
        a.setdefault("source", "manual")
        a.setdefault("status", "pending")
        conflict = staff_schedule.appointment_conflict(
            _staff_by_id.get(str(a.get("staff_id"))),
            _closures,
            a.get("date") or "",
            (a.get("time") or "").strip(),
        )
        if conflict:
            a["schedule_conflict"] = conflict
    holds = booking_service._voice_calendar_holds() if runtime.USE_DB else []
    diag = database.db_appointments_diagnostics(cid) if runtime.USE_DB else {}
    twilio_on_tenant = ((tenant or {}).get("twilio_phone_number") or "").strip() or None
    system_info(
        "appointments_list_loaded",
        client_id=cid,
        count=len(lst),
        calendar_holds=len(holds),
        orphans_removed=orphans_removed,
        likely_client_id_mismatch=bool(diag.get("likely_mismatch")),
        env_client_id=diag.get("env_client_id"),
        env_appointment_count=diag.get("env_client_id_appointment_count"),
        twilio_phone_configured=bool(twilio_on_tenant),
    )
    if runtime.USE_DB and holds and not lst:
        system_info(
            "appointments_list_empty_but_calendar_holds",
            client_id=cid,
            hold_count=len(holds),
            orphans_removed=orphans_removed,
            sample_hold=holds[0] if holds else None,
        )
    return {
        "appointments": lst,
        "client_id": cid,
        "calendar_holds": holds,
        "orphan_slots_removed": orphans_removed,
        "diagnostics": diag,
        "twilio_phone_number": twilio_on_tenant,
    }


@router.get("/api/appointments/diagnostics")
def get_appointments_diagnostics(
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Tenant-scoped appointment debug snapshot (for dashboard troubleshooting)."""
    cid = deps._bind_tenant_db_context(tenant)
    holds = booking_service._voice_calendar_holds() if runtime.USE_DB else []
    diag = database.db_appointments_diagnostics(cid) if runtime.USE_DB else {}
    return {
        "client_id": cid,
        "twilio_phone_number": ((tenant or {}).get("twilio_phone_number") or "").strip()
        or None,
        "calendar_holds": holds,
        **diag,
    }


@router.get("/api/appointments/calendar")
def appointments_calendar(
    date_from: str,
    date_to: str,
    staff_id: Optional[str] = None,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Return active appointments for calendar grid (excludes cancelled/rejected)."""
    if not runtime.USE_DB:
        return {"events": []}
    cid = deps._bind_tenant_db_context(tenant)
    events = database.db_appointments_in_date_range(date_from, date_to, staff_id, client_id=cid)
    slots_by_apt = booking_service._booked_slot_duration_by_appointment_id()
    services = config_service.get_business_info().get("services") or []
    enriched = []
    for apt in events:
        dm = booking_service._duration_minutes_for_appointment(apt, slots_by_apt, services)
        enriched.append({**apt, "duration_minutes": dm})
    return {"events": enriched}


@router.patch("/api/appointments/{appointment_id}")
def update_appointment(
    appointment_id: int,
    update: AppointmentUpdate,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Update appointment status or details. Used by the appointments frontend."""
    cid = deps._bind_tenant_db_context(tenant)
    kwargs = {}
    if update.status is not None:
        kwargs["status"] = update.status
    if update.date is not None:
        kwargs["date"] = update.date
    if update.time is not None:
        kwargs["time"] = update.time
    if update.reason is not None:
        kwargs["reason"] = update.reason
    if update.name is not None:
        kwargs["name"] = update.name
    if update.email is not None:
        kwargs["email"] = update.email
    if update.phone is not None:
        kwargs["phone"] = update.phone
    if runtime.USE_DB and kwargs:
        apt = database.db_appointments_update(appointment_id, client_id=cid, **kwargs)
        if apt:
            return {"success": True, "appointment": apt}
    else:
        for i, apt in enumerate(runtime.appointments):
            if apt["id"] == appointment_id:
                apt.update(kwargs)
                return {"success": True, "appointment": apt}
    raise HTTPException(status_code=404, detail="Appointment not found")


def _flag_if_confirmation_unsent(
    appointment_id: int, apt: dict, cid: str, sent: bool
) -> dict:
    """When a dashboard action could not deliver its confirmation text, persist a
    flag on the appointment so the dashboard surfaces 'text didn't send — call the
    customer' instead of silently reporting success. Guarded so an un-migrated DB
    (no confirmation_sms_failed column) degrades to a response-only flag.
    """
    if sent:
        return apt
    try:
        if runtime.USE_DB:
            updated = database.db_appointments_update(
                appointment_id, confirmation_sms_failed=True, client_id=cid
            )
            if updated:
                return updated
    except Exception:
        pass
    apt["confirmation_sms_failed"] = True
    return apt


@router.post("/api/appointments/{appointment_id}/accept")
def accept_appointment(
    appointment_id: int,
    request: Request,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Store accepted: mark appointment accepted and send confirmation SMS to customer."""
    cid = deps._bind_tenant_db_context(tenant)
    apt = (
        database.db_appointments_get_by_id(appointment_id, client_id=cid)
        if runtime.USE_DB
        else next((a for a in runtime.appointments if a["id"] == appointment_id), None)
    )
    if not apt:
        system_info(
            "appointment_accept_not_found",
            appointment_id=appointment_id,
            client_id=cid,
        )
        raise HTTPException(status_code=404, detail="Appointment not found")
    if str(apt.get("status") or "") != "pending_review":
        raise HTTPException(
            status_code=400, detail="Appointment is not awaiting approval"
        )
    if runtime.USE_DB:
        apt = (
            database.db_appointments_update(appointment_id, status="accepted", client_id=cid)
            or apt
        )
    else:
        apt["status"] = "accepted"
    deps.audit_log(
        "user",
        "appointment_accepted",
        resource_type="appointment",
        resource_id=str(appointment_id),
        details={"date": apt.get("date"), "time": apt.get("time")},
        request=request,
    )
    business_name = config_service.get_business_info().get("name", "us")
    date = apt.get("date", "")
    time_ampm = booking_service._hhmm_to_ampm(apt.get("time") or "")
    msg = f"Your appointment at {business_name} is confirmed for {date} at {time_ampm}. Reply if you need to change."
    sent = sms_service.send_sms(apt.get("phone") or "", msg, from_override=booking_service._tenant_sms_from_number())
    apt = _flag_if_confirmation_unsent(appointment_id, apt, cid, sent)
    return {"success": True, "appointment": apt, "confirmation_sms_sent": sent}


# ===== AI-polished decline/cancel routes (cut 2; need runtime.client) =====


class AppointmentRejectBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class PreviewDeclineSmsBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)
    appointment_id: Optional[int] = None
    # The dashboard sends its internal action name ("reject" for declining a pending request,
    # "cancel" for an accepted booking). Accept "reject" too — the handler maps it to "decline" —
    # so the SMS preview doesn't 422 and show "Could not generate preview".
    event: Literal["decline", "cancel", "reject"] = "decline"


_ACCEPTED_APPOINTMENT_STATUSES = frozenset({"accepted", "confirmed", "completed"})


@router.post("/api/appointments/{appointment_id}/reject")
def reject_appointment(
    appointment_id: int,
    body: AppointmentRejectBody,
    request: Request,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Reject request with owner-provided reason; AI-polished SMS to customer."""
    cid = deps._bind_tenant_db_context(tenant)
    apt = (
        database.db_appointments_get_by_id(appointment_id, client_id=cid)
        if runtime.USE_DB
        else next((a for a in runtime.appointments if a["id"] == appointment_id), None)
    )
    if not apt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if str(apt.get("status") or "") != "pending_review":
        raise HTTPException(
            status_code=400, detail="Appointment is not awaiting approval"
        )
    reason_clean = body.reason.strip()
    if runtime.USE_DB:
        apt = (
            database.db_appointments_update(
                appointment_id,
                status="rejected",
                owner_decline_reason=reason_clean,
                client_id=cid,
            )
            or apt
        )
    else:
        apt["status"] = "rejected"
    deps.audit_log(
        "user",
        "appointment_rejected",
        resource_type="appointment",
        resource_id=str(appointment_id),
        details={"date": apt.get("date"), "time": apt.get("time")},
        request=request,
    )
    booking_service.release_slot(appointment_id)
    business_name = config_service.get_business_info().get("name", "us")
    msg = booking_service.polish_owner_decline_sms(reason_clean, business_name, apt)
    sent = sms_service.send_sms(apt.get("phone") or "", msg, from_override=booking_service._tenant_sms_from_number())
    apt = _flag_if_confirmation_unsent(appointment_id, apt, cid, sent)
    return {"success": True, "appointment": apt, "confirmation_sms_sent": sent}


@router.post("/api/appointments/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: int,
    body: AppointmentRejectBody,
    request: Request,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Cancel an accepted booking, free the slot, and text the customer."""
    cid = deps._bind_tenant_db_context(tenant)
    apt = (
        database.db_appointments_get_by_id(appointment_id, client_id=cid)
        if runtime.USE_DB
        else next((a for a in runtime.appointments if a["id"] == appointment_id), None)
    )
    if not apt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    st = str(apt.get("status") or "")
    if st not in _ACCEPTED_APPOINTMENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Only accepted runtime.appointments can be cancelled from the dashboard",
        )
    reason_clean = body.reason.strip()
    if runtime.USE_DB:
        apt = (
            database.db_appointments_update(
                appointment_id,
                status="cancelled",
                owner_decline_reason=reason_clean,
                client_id=cid,
            )
            or apt
        )
    else:
        apt["status"] = "cancelled"
    deps.audit_log(
        "user",
        "appointment_cancelled",
        resource_type="appointment",
        resource_id=str(appointment_id),
        details={"date": apt.get("date"), "time": apt.get("time")},
        request=request,
    )
    booking_service.release_slot(appointment_id)
    business_name = config_service.get_business_info().get("name", "us")
    msg = booking_service.polish_owner_customer_sms(reason_clean, business_name, apt, event="cancel")
    sent = sms_service.send_sms(apt.get("phone") or "", msg, from_override=booking_service._tenant_sms_from_number())
    apt = _flag_if_confirmation_unsent(appointment_id, apt, cid, sent)
    system_info(
        "appointment_cancelled_by_store",
        appointment_id=appointment_id,
        client_id=cid,
        date=apt.get("date"),
        time=apt.get("time"),
    )
    return {"success": True, "appointment": apt, "confirmation_sms_sent": sent}


class AppointmentBulkDeleteBody(BaseModel):
    ids: list[int] = Field(default_factory=list)


@router.delete("/api/appointments/{appointment_id}")
def delete_appointment(
    appointment_id: int,
    request: Request,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Permanently remove one appointment (dashboard cleanup). Frees its slot; does NOT text
    the customer (use cancel for that). Tenant-scoped."""
    cid = deps._bind_tenant_db_context(tenant)
    if runtime.USE_DB:
        apt = database.db_appointments_get_by_id(appointment_id, client_id=cid)
        if not apt:
            raise HTTPException(status_code=404, detail="Appointment not found")
        booking_service.release_slot(appointment_id)
        database.db_appointments_delete(appointment_id, client_id=cid)
    else:
        before = len(runtime.appointments)
        runtime.appointments[:] = [
            a for a in runtime.appointments if a.get("id") != appointment_id
        ]
        if len(runtime.appointments) == before:
            raise HTTPException(status_code=404, detail="Appointment not found")
    deps.audit_log(
        "user",
        "appointment_deleted",
        resource_type="appointment",
        resource_id=str(appointment_id),
        request=request,
    )
    booking_service._invalidate_booked_slots_cache()
    system_info("appointment_deleted", appointment_id=appointment_id, client_id=cid)
    return {"success": True, "deleted": True}


@router.post("/api/appointments/bulk-delete")
def bulk_delete_appointments(
    body: AppointmentBulkDeleteBody,
    request: Request,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Permanently remove several appointments at once (e.g. clear cancelled or past). Frees
    each slot; does NOT text customers. Tenant-scoped."""
    cid = deps._bind_tenant_db_context(tenant)
    ids = [int(i) for i in (body.ids or [])][:1000]
    if not ids:
        return {"success": True, "deleted": 0}
    if runtime.USE_DB:
        for i in ids:
            booking_service.release_slot(i)
        count = database.db_appointments_delete_many(ids, client_id=cid)
    else:
        idset = set(ids)
        before = len(runtime.appointments)
        runtime.appointments[:] = [
            a for a in runtime.appointments if a.get("id") not in idset
        ]
        count = before - len(runtime.appointments)
    deps.audit_log(
        "user",
        "appointments_bulk_deleted",
        resource_type="appointment",
        details={"count": count, "requested": len(ids)},
        request=request,
    )
    booking_service._invalidate_booked_slots_cache()
    system_info("appointments_bulk_deleted", count=count, requested=len(ids), client_id=cid)
    return {"success": True, "deleted": count}


@router.post("/api/appointments/preview-decline-sms")
def preview_decline_sms(
    body: PreviewDeclineSmsBody,
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """Return AI-polished decline text without sending SMS (for owner review before reject)."""
    cid = deps._bind_tenant_db_context(tenant)
    apt: dict = {}
    if body.appointment_id is not None and runtime.USE_DB:
        apt = database.db_appointments_get_by_id(body.appointment_id, client_id=cid) or {}
        if not apt:
            raise HTTPException(status_code=404, detail="Appointment not found")
    business_name = config_service.get_business_info().get("name", "us")
    event = (body.event or "decline").strip().lower()
    if event not in ("decline", "cancel"):
        event = "decline"
    polished = booking_service.polish_owner_customer_sms(
        body.reason.strip(),
        business_name,
        apt if apt else {"date": "", "time": ""},
        event=event,
    )
    return {"polished_message": polished}
