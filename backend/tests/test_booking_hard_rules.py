"""Per-store booking guards: consult-only services and add-ons.

From the HairMasters service tree: corrective color must never be booked over the
phone ("Do not book this service, transfer the call to the salon"), and add-ons are
"not available as a stand alone service".

These are enforced in CODE, not only asked for in the prompt, because a model having
an off day must not be able to book them anyway.

The isolation tests are the important ones: both lists are empty for every store that
hasn't configured them, so no existing customer changes behavior.
"""

from __future__ import annotations

import pytest

import config_service


_SERVICES = [
    {"id": "s1", "name": "Shampoo & Haircut", "price": 28, "duration_minutes": 30},
    {"id": "s2", "name": "Corrective Color (charged by the hour)*", "price": 0, "duration_minutes": 60},
    {"id": "s3", "name": "Specialty Conditioner", "price": 0, "duration_minutes": 10, "is_addon": True},
    {"id": "s4", "name": "Master Stylist 5", "price": 5, "duration_minutes": 0, "is_addon": True},
]


def _configured(**over):
    data = {
        "name": "HairMasters Olympia",
        "hours": "Mon-Sat 9 AM - 7 PM",
        "services": _SERVICES,
        "staff": [{"id": "stf-1", "name": "Jamie", "service_ids": []}],
        "consult_only_services": ["Corrective Color"],
        "booking_rules": ["Fashion colors must be booked as Vivid color."],
    }
    data.update(over)
    return config_service._config_data_to_business_info(data)


def _plain():
    """A store that configured none of this — i.e. every other Nuvatra customer."""
    return config_service._config_data_to_business_info(
        {"name": "Normal Shop", "hours": "9-5", "services": [{"id": "x", "name": "Haircut"}]}
    )


# --- Config-level behavior ----------------------------------------------------


def test_consult_matches_loosely_in_both_directions():
    info = _configured()
    # Configured "Corrective Color" catches the fuller catalog name...
    assert config_service.service_requires_consult("Corrective Color (charged by the hour)*", info)
    # ...and a caller's shorter phrasing.
    assert config_service.service_requires_consult("corrective color", info)
    assert config_service.service_requires_consult("CORRECTIVE  COLOR", info)


def test_ordinary_service_is_not_consult_only():
    assert config_service.service_requires_consult("Shampoo & Haircut", _configured()) is False


def test_addon_can_be_restricted_to_specific_services():
    """From the real service tree: Master Stylist 5 is for cuts and styling, Master
    Stylist 10 for chemical services. Empty means it goes with anything."""
    info = config_service._config_data_to_business_info(
        {
            "services": [
                {"id": "cut", "name": "Haircut", "price": 28, "duration_minutes": 30},
                {"id": "color", "name": "All-over color", "price": 100, "duration_minutes": 120},
                {"id": "ms5", "name": "Master Stylist 5", "is_addon": True,
                 "applies_to_service_ids": ["cut"]},
                {"id": "olaplex", "name": "Olaplex", "is_addon": True},
            ]
        }
    )
    by_id = {s["id"]: s for s in info["services"]}
    assert by_id["ms5"]["applies_to_service_ids"] == ["cut"]
    assert by_id["olaplex"]["applies_to_service_ids"] == []   # unrestricted
    assert by_id["cut"]["applies_to_service_ids"] == []       # not an add-on at all


def test_references_to_deleted_services_are_dropped():
    """Deleting a service must not leave an add-on pointing at nothing — the prompt
    would render an empty restriction, making the add-on unofferable."""
    info = config_service._config_data_to_business_info(
        {
            "services": [
                {"id": "cut", "name": "Haircut", "price": 28, "duration_minutes": 30},
                {"id": "ms5", "name": "Master Stylist 5", "is_addon": True,
                 "applies_to_service_ids": ["cut", "deleted-service"]},
            ]
        }
    )
    ms5 = [s for s in info["services"] if s["id"] == "ms5"][0]
    assert ms5["applies_to_service_ids"] == ["cut"]


def test_an_addon_cannot_point_at_itself():
    info = config_service._config_data_to_business_info(
        {"services": [{"id": "a", "name": "Olaplex", "is_addon": True,
                       "applies_to_service_ids": ["a"]}]}
    )
    assert info["services"][0]["applies_to_service_ids"] == []


def test_prompt_states_which_services_an_addon_belongs_with():
    from prompts.receptionist import build_system_prompt

    info = config_service._config_data_to_business_info(
        {
            "name": "Salon",
            "hours": "9-5",
            "staff": [{"id": "s1", "name": "Jamie"}],
            "services": [
                {"id": "cut", "name": "Haircut", "price": 28, "duration_minutes": 30},
                {"id": "ms5", "name": "Master Stylist 5", "is_addon": True,
                 "applies_to_service_ids": ["cut"]},
                {"id": "olaplex", "name": "Olaplex", "is_addon": True},
            ],
        }
    )
    prompt = build_system_prompt(business_info=info)
    assert 'only with: "Haircut"' in prompt
    # An unrestricted add-on says so, rather than leaving the model to invent a rule.
    assert "goes with any service" in prompt


def test_addon_flag_round_trips():
    info = _configured()
    assert config_service.is_addon_service("Specialty Conditioner", info) is True
    assert config_service.is_addon_service("Master Stylist 5", info) is True
    assert config_service.is_addon_service("Shampoo & Haircut", info) is False


def test_services_default_to_not_addon():
    info = config_service._config_data_to_business_info(
        {"services": [{"id": "a", "name": "Haircut"}]}
    )
    assert info["services"][0]["is_addon"] is False


def test_rules_are_deduped_and_trimmed():
    """Whitespace trimmed, blanks dropped, case-insensitive duplicates collapsed."""
    info = config_service._config_data_to_business_info(
        {"booking_rules": ["  Ask hair length.  ", "ASK HAIR LENGTH.", "", "Second rule"]}
    )
    assert info["booking_rules"] == ["Ask hair length.", "Second rule"]


# --- Isolation: unconfigured stores are untouched -----------------------------


def test_unconfigured_store_has_no_rules():
    info = _plain()
    assert info["consult_only_services"] == []
    assert info["booking_rules"] == []


def test_unconfigured_store_blocks_nothing():
    """The regression guard for every existing customer: even a service literally
    named 'Corrective Color' books normally if the store never configured the rule."""
    info = _plain()
    assert config_service.service_requires_consult("Corrective Color", info) is False
    assert config_service.service_requires_consult("anything at all", info) is False
    assert config_service.is_addon_service("Haircut", info) is False


# --- Structural guards in the booking path ------------------------------------


def _booking(**over):
    b = {
        "name": "Shannon",
        "phone": "+14155550101",
        "email": "",
        "date": "2099-06-15",
        "time": "14:00",
        "reason": "Shampoo & Haircut",
        "staff": "",
    }
    b.update(over)
    return b


def _patch(monkeypatch, biz):
    import conversation_service as cs

    inserted = []
    monkeypatch.setattr("config_service.get_business_info", lambda: biz)
    monkeypatch.setattr(cs.runtime, "USE_DB", True)
    monkeypatch.setattr(
        cs.database, "db_appointments_insert",
        lambda d: (inserted.append(d), {"id": 1, **d})[1],
    )
    monkeypatch.setattr(cs.database, "set_request_client_id", lambda cid: None)
    monkeypatch.setattr(cs.database, "_client_id", lambda: "shop")
    monkeypatch.setattr(cs.booking_service, "is_slot_available", lambda *a, **k: True)
    monkeypatch.setattr(cs.booking_service, "reserve_slot", lambda *a, **k: True)
    monkeypatch.setattr(cs, "_supersede_pending_customer_drafts_for_slot", lambda *a, **k: None)
    return cs, inserted


@pytest.mark.parametrize(
    "service", ["Corrective Color", "corrective color", "Corrective Color (charged by the hour)*"]
)
def test_consult_only_service_is_never_booked(monkeypatch, service):
    cs, inserted = _patch(monkeypatch, _configured())
    out = cs._create_appointment_from_booking(_booking(reason=service), client_id_override="shop")
    assert out is None
    assert inserted == [], "a consult-only service must never reach the calendar"


@pytest.mark.parametrize("service", ["Specialty Conditioner", "Master Stylist 5"])
def test_addon_alone_is_never_booked(monkeypatch, service):
    cs, inserted = _patch(monkeypatch, _configured())
    out = cs._create_appointment_from_booking(_booking(reason=service), client_id_override="shop")
    assert out is None
    assert inserted == []


def test_normal_service_still_books_at_a_configured_store(monkeypatch):
    """The guards must be surgical — everything else at that store still works."""
    cs, inserted = _patch(monkeypatch, _configured())
    out = cs._create_appointment_from_booking(
        _booking(reason="Shampoo & Haircut"), client_id_override="shop"
    )
    assert out is not None
    assert len(inserted) == 1


def test_unconfigured_store_books_everything_as_before(monkeypatch):
    """Every other customer: nothing is blocked, including names that would be
    blocked at a store that configured the rule."""
    cs, inserted = _patch(monkeypatch, _plain())
    for service in ("Haircut", "Corrective Color", "Specialty Conditioner"):
        inserted.clear()
        out = cs._create_appointment_from_booking(
            _booking(reason=service), client_id_override="shop"
        )
        assert out is not None, f"{service} should book normally at an unconfigured store"
        assert len(inserted) == 1


# --- Prompt rendering ---------------------------------------------------------


def test_prompt_marks_addons_and_lists_rules():
    from prompts.receptionist import build_system_prompt

    prompt = build_system_prompt(business_info=_configured())
    assert "ADD-ON only" in prompt
    assert "NEVER BOOK" in prompt
    assert "Corrective Color" in prompt
    assert "Fashion colors must be booked as Vivid color." in prompt


# --- Saving the config through the API ---------------------------------------


def test_update_model_accepts_the_booking_fields():
    """The PATCH body must actually carry these, or the Settings UI writes nothing."""
    from routers.business import BusinessInfoUpdate

    body = BusinessInfoUpdate(
        booking_mode="external",
        booking_provider_name="Zenoti",
        consult_only_services=["Corrective Color"],
        booking_rules=["Fashion colors must be booked as Vivid color."],
    )
    assert body.booking_mode == "external"
    assert body.booking_provider_name == "Zenoti"
    assert body.consult_only_services == ["Corrective Color"]
    assert body.booking_rules == ["Fashion colors must be booked as Vivid color."]


def test_update_model_rejects_an_unknown_booking_mode():
    """Only the two real modes are accepted — a typo is a 422, not a silent default."""
    import pydantic

    from routers.business import BusinessInfoUpdate

    with pytest.raises(pydantic.ValidationError):
        BusinessInfoUpdate(booking_mode="zenoti")


def test_booking_fields_are_optional():
    """Every other Settings save must keep working without sending them."""
    from routers.business import BusinessInfoUpdate

    body = BusinessInfoUpdate(name="Just a rename")
    assert body.booking_mode is None
    assert body.consult_only_services is None
    assert body.booking_rules is None


def test_addon_flag_survives_a_service_save():
    """Services round-trip through _normalize_service_entries on write, so an add-on
    marked in Settings has to still be an add-on after saving."""
    saved = config_service._normalize_service_entries(
        [
            {"id": "s1", "name": "Haircut", "price": 28, "duration_minutes": 30},
            {"id": "s2", "name": "Olaplex", "price": 20, "duration_minutes": 10, "is_addon": True},
        ]
    )
    assert saved[0]["is_addon"] is False
    assert saved[1]["is_addon"] is True


def test_an_addon_keeps_a_zero_duration_through_a_save():
    """Master Stylist 5 is a $5 charge, not five minutes. The old floor of 5 rewrote
    the imported 0, which would pad any appointment the add-on joins."""
    saved = config_service._normalize_service_entries(
        [{"id": "ms5", "name": "Master Stylist 5", "duration_minutes": 0, "is_addon": True}]
    )
    assert saved[0]["duration_minutes"] == 0


def test_a_bookable_service_still_floors_at_five_minutes():
    """The floor exists so a real appointment can't be zero-length — only add-ons are
    exempt."""
    saved = config_service._normalize_service_entries(
        [{"id": "cut", "name": "Haircut", "duration_minutes": 0}]
    )
    assert saved[0]["duration_minutes"] == 5


def test_category_survives_a_save():
    """The import reads "Color Services" off the spreadsheet; staff assignment groups
    by it, so dropping it on save would empty every group."""
    saved = config_service._normalize_service_entries(
        [
            {"id": "c1", "name": "All-over color", "category": "Color Services"},
            {"id": "c2", "name": "Haircut"},
        ]
    )
    assert saved[0]["category"] == "Color Services"
    assert saved[1]["category"] == "", "no category is empty, never None"


def test_legacy_string_services_get_an_empty_category():
    saved = config_service._normalize_service_entries(["Haircut", "Color"])
    assert [s["category"] for s in saved] == ["", ""]


# --- Request mode has to reach the words, not just the database -------------
# A real call proved the gap: the store was in external mode, the appointment was
# correctly filed as a request, and the caller was still told "I'll book you for a
# shampoo and haircut at 2 PM on Thursday" and texted "your appointment info on
# file". The database was the only honest party in the transaction.


def _external(**over):
    data = {
        "name": "HairMasters",
        "hours": "Mon-Fri 9 AM - 5 PM",
        "booking_mode": "external",
        "booking_provider_name": "Zenoti",
        "services": [{"id": "s1", "name": "Shampoo & Haircut", "price": 28, "duration_minutes": 30}],
        "staff": [{"id": "stf-1", "name": "Jamie", "service_ids": []}],
    }
    data.update(over)
    return config_service._config_data_to_business_info(data)


def test_request_mode_forbids_claiming_availability():
    from prompts.receptionist import build_system_prompt

    prompt = build_system_prompt(business_info=_external(), include_booked_slots=True)
    assert "REQUEST ONLY" in prompt
    assert "YOU CANNOT SEE THE CALENDAR" in prompt
    assert "Zenoti" in prompt, "name the system so the AI knows where the calendar is"
    assert "NEVER say a day or time is available" in prompt


def test_request_mode_withdraws_permission_to_say_booked():
    """Rule (6) normally allows "you're booked" once BOOKING is emitted. In request
    mode that permission has to be revoked, or it contradicts the block above and —
    being later in the prompt — tends to win."""
    from prompts.receptionist import build_system_prompt

    prompt = build_system_prompt(business_info=_external(), include_booked_slots=True)
    assert "not even after you output BOOKING" in prompt


def test_internal_mode_keeps_the_original_confirmation_rule():
    """Every store on the default mode must be word-for-word unchanged."""
    from prompts.receptionist import build_system_prompt

    prompt = build_system_prompt(business_info=_configured(), include_booked_slots=True)
    assert "REQUEST ONLY" not in prompt
    assert "until you output BOOKING on that same turn" in prompt
    assert "not even after you output BOOKING" not in prompt


def test_a_store_with_no_provider_name_still_gets_the_block():
    from prompts.receptionist import build_system_prompt

    prompt = build_system_prompt(
        business_info=_external(booking_provider_name=""), include_booked_slots=True
    )
    assert "REQUEST ONLY" in prompt
    assert "(it lives in" not in prompt, "don't render an empty parenthetical"


def test_the_request_sms_says_nothing_is_booked_yet():
    import booking_service

    apt = {
        "name": "Raj Gill", "phone": "+14155550101", "date": "2026-08-13",
        "time": "14:00", "reason": "Shampoo & Haircut", "status": "pending_review",
    }
    msg = booking_service._format_appointment_details_confirmation_sms(apt)
    assert "nothing is booked yet" in msg
    assert "they'll confirm" in msg
    # The old fall-through wording read like a confirmation of something that existed.
    assert "appointment info on file" not in msg
    assert "YES or CONFIRM" not in msg, "there is no slot for the customer to reserve"


def test_the_internal_confirmation_texts_are_unchanged():
    import booking_service

    base = {
        "name": "Raj", "phone": "+14155550101", "date": "2026-08-13",
        "time": "14:00", "reason": "Haircut",
    }
    pending = booking_service._format_appointment_details_confirmation_sms(
        {**base, "status": "pending_customer"}
    )
    assert "YES or CONFIRM" in pending
    other = booking_service._format_appointment_details_confirmation_sms(
        {**base, "status": "confirmed"}
    )
    assert "appointment info on file" in other


def test_prompt_for_an_unconfigured_store_has_none_of_it():
    from prompts.receptionist import build_system_prompt

    prompt = build_system_prompt(business_info=_plain())
    assert "ADD-ON only" not in prompt
    assert "NEVER BOOK" not in prompt
    assert "BOOKING POLICIES" not in prompt
