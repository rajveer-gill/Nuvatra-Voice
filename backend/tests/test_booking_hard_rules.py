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


def test_prompt_for_an_unconfigured_store_has_none_of_it():
    from prompts.receptionist import build_system_prompt

    prompt = build_system_prompt(business_info=_plain())
    assert "ADD-ON only" not in prompt
    assert "NEVER BOOK" not in prompt
    assert "BOOKING POLICIES" not in prompt
