"""Appointments API — CRUD + accept (booking creation/calendar/status).

The AI-polished decline/cancel routes (reject, cancel, preview-decline-sms) stay in
main for now — they depend on polish_owner_*_sms, which couples to the OpenAI client
(a shared runtime piece deferred to its own extraction). They move once that lands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

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


class AppointmentUpdate(BaseModel):
    status: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    reason: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


@router.post("/api/appointments")
async def create_appointment(
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
            booking_service.reserve_slot(
                date, time, appointment_id, duration_min, staff_key
            )
        appointment_data["id"] = appointment_id
        appointment_data.setdefault("created_at", datetime.now().isoformat())
        return {"success": True, "appointment": appointment_data}
    except HTTPException:
        raise
    except Exception as e:
        raise deps._server_error("create appointment failed", e)


@router.get("/api/appointments")
async def get_appointments(
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    cid = deps._bind_tenant_db_context(tenant)
    orphans_removed = booking_service._reconcile_booked_slots_orphans() if runtime.USE_DB else 0
    lst = database.db_appointments_get_all(client_id=cid) if runtime.USE_DB else runtime.appointments
    for a in lst:
        a.setdefault("source", "manual")
        a.setdefault("status", "pending")
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
async def get_appointments_diagnostics(
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
async def appointments_calendar(
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
async def update_appointment(
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


@router.post("/api/appointments/{appointment_id}/accept")
async def accept_appointment(
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
    sms_service.send_sms(apt.get("phone") or "", msg, from_override=booking_service._tenant_sms_from_number())
    return {"success": True, "appointment": apt}
