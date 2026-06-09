"""Core misc routes — AI conversation (text channel), messages, and email-notify helper.

Thin transport over the extracted services (conversation_service / booking_service /
config_service / deps / database / runtime).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import booking_service
import config_service
import conversation_service
import database
import deps
import runtime
from observability import email_hint_for_log, system_info
from booking_fields import booking_context_from_business, is_valid_booking_date, looks_like_booking_time

router = APIRouter()


class ConversationRequest(BaseModel):
    message: str
    session_id: str
    conversation_history: Optional[List[dict]] = []


class ConversationResponse(BaseModel):
    response: str
    action: Optional[str] = None
    data: Optional[dict] = None


class MessageRequest(BaseModel):
    caller_name: str
    caller_phone: str
    message: str
    urgency: str = "normal"


def _send_appointment_email_notification(apt: dict, *, kind: str) -> bool:
    """Send submitted/confirmed email when enabled and provider is configured."""
    if not booking_service._appointment_email_enabled():
        return False
    from email_notify import format_appointment_email, send_appointment_email

    email = (apt.get("email") or "").strip()
    if not email:
        return False
    business_name = (config_service.get_business_info().get("name") or "us").strip()
    subject, html, text = format_appointment_email(
        kind=kind,
        business_name=business_name,
        customer_name=(apt.get("name") or "").strip(),
        date=apt.get("date") or "",
        time_ampm=booking_service._hhmm_to_ampm(apt.get("time") or ""),
        service=(apt.get("reason") or "").strip(),
    )
    ok = send_appointment_email(
        to=email, subject=subject, html_body=html, text_body=text
    )
    from observability import email_hint_for_log

    system_info(
        "appointment_email_notification",
        apt_id=apt.get("id"),
        kind=kind,
        sent=ok,
        email_hint=email_hint_for_log(email),
    )
    return ok


@router.post("/api/conversation", response_model=ConversationResponse)
async def handle_conversation(
    request: ConversationRequest, _: None = Depends(deps.require_active_subscription)
):
    try:
        # Always include booked slots so the AI knows which times are taken and avoids double-booking
        system_content = conversation_service.get_system_prompt(include_booked_slots=True)
        messages = [{"role": "system", "content": system_content}]
        if request.conversation_history:
            runtime.messages.extend(request.conversation_history)
        runtime.messages.append({"role": "user", "content": request.message})

        response = runtime.client.chat.completions.create(
            model="gpt-3.5-turbo", messages=runtime.messages, temperature=0.7, max_tokens=200
        )

        ai_response = response.choices[0].message.content
        action = None
        data = None

        # BOOKING: create appointment from AI output if present
        booking = conversation_service.parse_booking(ai_response)
        if booking:
            booking, repairs, reject = conversation_service._prepare_parsed_booking(booking)
            if reject:
                system_info(
                    "chat_booking_line_rejected",
                    reason=reject,
                    repairs=repairs or None,
                )
                booking = None
            elif repairs:
                system_info("chat_booking_line_repaired", repairs=repairs)
        if booking:
            ok_booking, fail_msg, _, canonical_service = conversation_service._validate_booking_requirements(
                booking
            )
            if not ok_booking:
                apt = None
            else:
                if canonical_service:
                    booking["reason"] = canonical_service
                apt = conversation_service._create_appointment_from_booking(booking)
            if apt:
                ai_response = f"You're all set! We have you down for {apt['date']} at {booking_service._hhmm_to_ampm(apt.get('time', '') or '')}. The store will confirm shortly."
                action = "schedule_appointment"
                data = {"appointment_id": apt["id"]}
            else:
                ctx = booking_context_from_business(config_service.get_business_info())
                name_ok = bool((booking.get("name") or "").strip())
                date_ok = is_valid_booking_date(booking.get("date"))
                time_ok = looks_like_booking_time(booking.get("time"), ctx)
                if not ok_booking:
                    ai_response = (
                        fail_msg
                        or "Before I can book this, please choose a stylist and service."
                    )
                elif not name_ok:
                    ai_response = "I'd love to book that for you—what's your name?"
                elif not date_ok or not time_ok:
                    ai_response = "I need the date and time again to confirm—which day and time would you like?"
                else:
                    ai_response = "That time slot just got booked. Would you like to try another time or another day?"

        ai_response = conversation_service._strip_booking_directive_for_voice(ai_response or "")
        if (
            "schedule" in request.message.lower()
            or "appointment" in request.message.lower()
        ):
            action = action or "schedule_appointment"
        elif (
            "message" in request.message.lower()
            or "leave a message" in request.message.lower()
        ):
            action = "take_message"
        elif (
            "transfer" in request.message.lower()
            or "department" in request.message.lower()
        ):
            action = "route_call"

        return ConversationResponse(response=ai_response, action=action, data=data)

    except Exception as e:
        raise deps._server_error("conversation endpoint failed", e)


@router.post("/api/messages")
async def create_message(
    message: MessageRequest, _: None = Depends(deps.require_active_subscription)
):
    try:
        data = {
            "caller_name": message.caller_name,
            "caller_phone": message.caller_phone,
            "message": message.message,
            "urgency": message.urgency,
            "status": "unread",
        }
        if runtime.USE_DB:
            message_data = database.db_messages_insert(data)
        else:
            message_data = {
                "id": len(runtime.messages) + 1,
                **data,
                "created_at": datetime.now().isoformat(),
            }
            runtime.messages.append(message_data)
        return {"success": True, "message": message_data}
    except Exception as e:
        raise deps._server_error("create message failed", e)


@router.get("/api/messages")
async def get_messages(_: None = Depends(deps.require_active_subscription)):
    lst = database.db_messages_get_all() if runtime.USE_DB else runtime.messages
    return {"messages": lst}
