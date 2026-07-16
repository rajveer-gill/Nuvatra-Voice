"""The MESSAGE: directive must outrank the off-topic 'always offer to book' steering.

Regression: a live call where the caller said "Tell them that I like to eat tacos." got
"Sure, I'll pass that along. Anyway, would you like to book an appointment?" — the model
followed "always close by offering to book" and DROPPED the MESSAGE: line, so the message
was silently lost (no voice_message_captured, nothing in the inbox).
"""
from prompts.receptionist import appointment_focus_guidance, build_system_prompt

BIZ = {
    "name": "Super Cuts",
    "hours": "Mon-Fri 9-5",
    "services": [{"id": "s1", "name": "Long Cut", "price": 50}],
    "staff": [{"id": "st1", "name": "Jake", "service_ids": ["s1"]}],
}


def test_focus_guidance_subordinates_booking_offer_to_directives():
    text = appointment_focus_guidance("Super Cuts", include_booked_slots=True, channel="voice")
    low = text.lower()
    # The booking offer must no longer be stated as unconditional ("always close by offering").
    assert "always close by offering to book" not in low
    # And the directive carve-out must be present.
    assert "message:" in low
    assert "required" in low


def test_system_prompt_forbids_claiming_a_message_without_the_directive():
    p = build_system_prompt(business_info=BIZ, include_booked_slots=True)
    low = p.lower()
    # The exact failure mode must be called out: saying "I'll pass that along" with no MESSAGE: line.
    assert "i'll pass that along" in low
    assert "silently lost" in low
    # The booking offer must never displace the directive.
    assert "take the place of the message: line" in low
