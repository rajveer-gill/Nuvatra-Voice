"""The stylist-suggestion nudge must list only stylists who provide the chosen service.

Regression for gpt-4o/Haiku over-listing stylists (offering one who doesn't do the service).
"""
import conversation_service as cs

BIZ = {
    "name": "Gills Salons",
    "services": [
        {"id": "svc_long", "name": "Long Cut"},
        {"id": "svc_short", "name": "Short Cut"},
    ],
    "staff": [
        {"id": "st_j", "name": "Jake", "service_ids": ["svc_long"]},
        {"id": "st_t", "name": "Tom", "service_ids": ["svc_long", "svc_short"]},
        {"id": "st_a", "name": "Andrew", "service_ids": ["svc_short"]},  # short only
    ],
}


def test_stylists_offering_service_excludes_ineligible():
    names = cs._stylists_offering_service(BIZ, "Long Cut")
    assert "Jake" in names and "Tom" in names
    assert "Andrew" not in names  # Andrew doesn't do long cuts


def test_no_nudge_once_appointment_created(monkeypatch):
    """Regression: after a booking lands, the nudge must go silent. Otherwise a caller who
    keeps talking ("Okay, thanks!") gets nudged into a SECOND BOOKING: line — which created a
    duplicate appointment AND a duplicate confirmation SMS on a real call."""
    monkeypatch.setattr(cs.config_service, "get_business_info", lambda: BIZ)
    history = [
        {"role": "user", "content": "I'd like to book a long cut with Jake"},
        {"role": "assistant", "content": "Sure! Which day?"},
        {"role": "user", "content": "Friday at 2 PM, I'm Alex"},
        {"role": "assistant", "content": "Booked! We'll text you to confirm."},
        {"role": "user", "content": "Okay."},  # the turn that caused the duplicate
    ]
    # Booking already created this call -> absolutely no nudge.
    assert cs._voice_booking_nudge_message(history, info=BIZ, appointment_created=True) is None
    # Sanity: without a booking, the nudge still fires (guard isn't just disabling everything).
    assert cs._voice_booking_nudge_message(history, info=BIZ, appointment_created=False) is not None


def test_nudge_lists_only_eligible_stylists(monkeypatch):
    # Keep every helper reading the same in-memory tenant (no DB).
    monkeypatch.setattr(cs.config_service, "get_business_info", lambda: BIZ)
    history = [
        {"role": "user", "content": "I'd like to book an appointment"},
        {"role": "assistant", "content": "Sure! What service? We offer Long Cut or Short Cut."},
        {"role": "user", "content": "A long cut, please."},
    ]
    msg = cs._voice_booking_nudge_message(history, info=BIZ)
    assert msg is not None
    assert "Long Cut" in msg
    assert "Jake" in msg and "Tom" in msg
    assert "Andrew" not in msg  # must NOT be suggested for a long cut
