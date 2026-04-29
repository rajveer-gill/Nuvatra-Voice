"""
System prompt for the voice receptionist.

Used by the Twilio voice pipeline. Business context and booked-slot lines are
injected by the caller (typically main.py) so this module stays free of DB/Twilio imports.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional


def build_system_prompt(
    *,
    business_info: dict,
    detected_language: str = "English",
    caller_memory: Optional[dict] = None,
    include_booked_slots: bool = False,
    booked_slots_prompt_text: Optional[str] = None,
) -> str:
    """
    Build the GPT system prompt for one voice turn.

    Args:
        business_info: Tenant/business dict from get_business_info().
        detected_language: Caller language label (e.g. English, Spanish).
        caller_memory: Optional repeat-caller metadata.
        include_booked_slots: When True, append slot rules and BOOKING: format instructions.
        booked_slots_prompt_text: Output of get_booked_slots_prompt_text when include_booked_slots;
            may be empty string when no slots are booked.
    """
    name = (business_info.get("name") or "the business").strip()
    hours = (business_info.get("hours") or "").strip()
    address = (business_info.get("address") or "").strip()
    services_list = ", ".join(business_info.get("services") or [])
    specials_list = " | ".join(business_info.get("specials") or [])
    reservation_info = " | ".join(business_info.get("reservation_rules") or [])
    menu_link = (business_info.get("menu_link") or "").strip()
    departments = business_info.get("departments") or []
    staff = business_info.get("staff") or []
    business_type = (business_info.get("business_type") or "").strip()

    help_lines: List[str] = []
    if hours:
        help_lines.append(f"- Hours: {hours}")
    if address:
        help_lines.append(f"- Location: {address}")
    if services_list:
        help_lines.append(f"- Services: {services_list}")
    if specials_list:
        help_lines.append(f"- Specials / promotions: {specials_list}")
    if reservation_info:
        help_lines.append(f"- Booking / appointment policies: {reservation_info}")
    if menu_link:
        help_lines.append(f"- More info / menu: {menu_link}")
    if departments:
        help_lines.append(f"- Routing to: {', '.join(departments)}")

    staff_block = ""
    if staff:
        staff_names = [s.get("name", "") for s in staff if s.get("name")]
        staff_block = (
            f"\n- Staff you can transfer to: {', '.join(staff_names)}. "
            "When the caller asks to speak to one of these people by name, reply with EXACTLY: "
            "TRANSFER_TO: [Name] (use the exact name from the list). Otherwise do not use TRANSFER_TO."
        )

    memory_block = ""
    if caller_memory and isinstance(caller_memory, dict):
        mem_name = caller_memory.get("name") or "there"
        count = caller_memory.get("call_count", 0)
        last = caller_memory.get("last_reason") or "general inquiry"
        memory_block = (
            f"\n- This is a REPEAT CALLER. Greet them warmly; you may say welcome back. "
            f"Name if we have it: {mem_name}. They have called {count} time(s) before; last time: {last}."
        )

    slots_block = ""
    if include_booked_slots:
        slots_text = booked_slots_prompt_text or ""
        if slots_text.strip():
            slots_block = (
                f"\n- {slots_text}\n"
                "- CRITICAL: Times listed above (with AM/PM) are TAKEN. When the prompt says "
                "'ONLY suggest these times' for a date, suggest ONLY those times—never suggest a time "
                "that is 'already taken' for that date. If the list is empty, all times are available."
            )
        else:
            slots_block = (
                "\n- Booked slots: none. CRITICAL: There are no booked slots, so ALL times are available. "
                "Never say a slot or day is 'taken', 'not available', or 'fully booked'—every time the caller "
                "asks for is available. Offer to book their requested time."
            )
        today_utc = datetime.now(timezone.utc).date()
        today_str = today_utc.isoformat()
        tomorrow_str = (today_utc + timedelta(days=1)).isoformat()
        slots_block += f"""
- TIMES: Always say times in 12-hour format with AM/PM (e.g. 9:00 AM, 2:30 PM). Never use 24-hour/military time (no 13:00, 14:00, etc.) when speaking to the caller.
- AVAILABILITY: When offering a time to book, use ONLY a time from the 'ONLY suggest these times' list for that day (if present). Never offer or say "we have an open slot at" a time that is listed as already taken. If they ask for availability for a day, suggest only the free times listed for that day.
- If they request a time that IS in the booked/taken list: politely say it's taken and suggest one of the free times from the list.
- CALLER PHONE: We already have the caller's phone number from this call—do NOT ask for it. Never say "please provide your phone number" or "what's your number". We will fill it in automatically. Only ask for: name (if needed), date and time, and optionally email for confirmations.
- When they have confirmed (name, date, time, service) and the slot is available (either not in the list or list is empty), reply with EXACTLY: BOOKING: name|phone|email|date|time|reason (| separator). RULES: (1) You MUST include the caller's name—if they haven't given it, ask for their name first, then output BOOKING. (2) For phone: leave empty (we have it from the call). (3) If you don't have their email yet, ask for it before outputting BOOKING so we can send confirmations (leave email empty if they decline). (4) Date must be YYYY-MM-DD. Today is {today_str}, tomorrow is {tomorrow_str}; use the correct calendar date (e.g. "tomorrow" = {tomorrow_str}). (5) Time as HH:MM (e.g. 13:00 for 1 PM). (6) Do not output BOOKING until you have at least name, date, and time."""

    help_section = (
        "\n".join(help_lines)
        if help_lines
        else "- (Business details: ask the caller what they need and offer to transfer or take a message.)"
    )
    if business_type:
        header = (
            f"Super peppy, warm AI receptionist for {name}, a {business_type}! "
            'Be EXTRA POSITIVE and ENTHUSIASTIC! Use peppy phrases like "absolutely!", "wonderful!", "awesome!". '
            "Keep responses to 1 sentence max. Be warm, brief, and make callers feel amazing!"
        )
    else:
        header = (
            f"Super peppy, warm AI receptionist for {name}! "
            'Be EXTRA POSITIVE and ENTHUSIASTIC! Use peppy phrases like "absolutely!", "wonderful!", "awesome!". '
            "Keep responses to 1 sentence max. Be warm, brief, and make callers feel amazing!"
        )

    base_prompt = f"""{header}

You can help with:
{help_section}{staff_block}{memory_block}{slots_block}"""

    if detected_language != "English":
        return (
            f"{base_prompt} CRITICAL INSTRUCTION: The caller is currently speaking in {detected_language}. "
            f"You MUST respond ONLY in {detected_language}. Do NOT respond in English or any other language. "
            f"Every word of your response must be in {detected_language}. "
            "If the caller switches languages, adapt immediately and respond in their new language."
        )
    return (
        f"{base_prompt} IMPORTANT: Respond in English. "
        "If the caller switches to another language, detect it and respond in that language immediately."
    )
