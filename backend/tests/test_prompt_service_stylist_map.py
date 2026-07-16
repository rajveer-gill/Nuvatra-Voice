"""The system prompt must state, unconditionally, which stylists provide each service.

The per-stylist roster ("Jake: Long Cut") makes the model invert and filter the list to answer
"who can do a long cut?" — and it over-listed on a real staging call, naming Andrew (short cuts
only) for a long cut and then defending it when challenged. The booking nudge injects the
computed list but only fires on a narrow trigger, so the constraint has to live in the prompt.
"""
from prompts.receptionist import build_system_prompt

# Mirrors the real Gills Salons roster that produced the bug.
BIZ = {
    "name": "Test Salon",
    "hours": "Mon-Fri 9am-5pm",
    "services": [
        {"id": "svc_short", "name": "Short Cut", "price": 35},
        {"id": "svc_long", "name": "Long Cut", "price": 55},
    ],
    "staff": [
        {"id": "st_jake", "name": "Jake", "service_ids": ["svc_long"]},
        {"id": "st_andrew", "name": "Andrew", "service_ids": ["svc_short"]},
        {"id": "st_tom", "name": "Tom", "service_ids": ["svc_short", "svc_long"]},
    ],
}


def _service_line(prompt: str, service: str) -> str:
    for line in prompt.splitlines():
        if line.strip().startswith(f"• {service}:"):
            return line
    raise AssertionError(f"no service→stylist line for {service!r} in prompt")


def test_prompt_lists_only_eligible_stylists_per_service():
    p = build_system_prompt(business_info=BIZ, include_booked_slots=True)
    long_cut = _service_line(p, "Long Cut")
    assert "Jake" in long_cut and "Tom" in long_cut
    assert "Andrew" not in long_cut  # short cuts only — the exact live bug

    short_cut = _service_line(p, "Short Cut")
    assert "Andrew" in short_cut and "Tom" in short_cut
    assert "Jake" not in short_cut  # long cuts only


def test_prompt_forbids_naming_other_stylists():
    p = build_system_prompt(business_info=BIZ, include_booked_slots=True)
    assert "name ONLY the stylists on that service's line" in p


def test_stylist_with_no_service_ids_provides_everything():
    """Empty service_ids means "does everything" — must match
    conversation_service._stylists_offering_service so the prompt and the booking guard agree."""
    biz = {
        **BIZ,
        "staff": [
            {"id": "st_jake", "name": "Jake", "service_ids": ["svc_long"]},
            {"id": "st_sam", "name": "Sam", "service_ids": []},
        ],
    }
    p = build_system_prompt(business_info=biz, include_booked_slots=True)
    assert "Sam" in _service_line(p, "Short Cut")
    assert "Sam" in _service_line(p, "Long Cut")
    assert "Jake" not in _service_line(p, "Short Cut")
