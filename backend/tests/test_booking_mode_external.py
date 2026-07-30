"""External (request-mode) booking, for stores whose real calendar lives elsewhere.

The Gill Salons / HairMasters stores run on Zenoti, which refused API access, so we
can't write to their calendar. Those stores capture *requests* that staff approve and
enter on their side.

The most important tests here are the isolation ones: every other Nuvatra customer is
"internal" by default and must behave exactly as before.
"""

from __future__ import annotations

import pytest

import config_service


# --- The default is the safety guarantee ---------------------------------------


def test_booking_mode_defaults_to_internal():
    """A config with no booking_mode — i.e. every existing customer — is internal."""
    info = config_service._config_data_to_business_info({"business_name": "Old Client"})
    assert info["booking_mode"] == "internal"
    assert config_service.is_external_booking(info) is False


def test_unknown_booking_mode_floors_to_internal():
    """A typo must not silently stop a store from booking."""
    for bad in ("zenoti", "EXTERNEL", "", None, "true", 1):
        info = config_service._config_data_to_business_info({"booking_mode": bad})
        assert info["booking_mode"] == "internal", bad
        assert config_service.is_external_booking(info) is False


def test_external_mode_is_recognized_case_insensitively():
    for good in ("external", "External", "  EXTERNAL  "):
        info = config_service._config_data_to_business_info({"booking_mode": good})
        assert info["booking_mode"] == "external"
        assert config_service.is_external_booking(info) is True


def test_provider_name_is_carried_for_display():
    info = config_service._config_data_to_business_info(
        {"booking_mode": "external", "booking_provider_name": "Zenoti"}
    )
    assert info["booking_provider_name"] == "Zenoti"


# --- Request-mode creation behavior -------------------------------------------

_BIZ_BASE = {
    "name": "HairMasters Olympia",
    "hours": "Mon-Sat 9 AM - 7 PM",
    "services": [{"id": "svc-cut", "name": "Shampoo & Haircut", "price": 0, "duration_minutes": 30}],
    "staff": [{"id": "stf-1", "name": "Jamie", "service_ids": []}],
    "timezone": "America/Los_Angeles",
}


def _biz(**over):
    out = dict(_BIZ_BASE)
    out.update(over)
    return config_service._config_data_to_business_info(out)


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


def _patch_common(monkeypatch, biz, *, inserted):
    """Wire conversation_service so creation runs without a DB."""
    import conversation_service as cs

    monkeypatch.setattr("config_service.get_business_info", lambda: biz)
    monkeypatch.setattr(cs.runtime, "USE_DB", True)
    monkeypatch.setattr(
        cs.database, "db_appointments_insert",
        lambda data: (inserted.append(data), {"id": 4242, **data})[1],
    )
    monkeypatch.setattr(cs.database, "set_request_client_id", lambda cid: None)
    monkeypatch.setattr(cs.database, "_client_id", lambda: "hm-olympia")
    return cs


def test_external_request_lands_in_the_approval_queue(monkeypatch):
    """A request must go straight to pending_review (staff approval), NOT sit in
    pending_customer waiting for an SMS reply the older caller may never send."""
    inserted = []
    cs = _patch_common(monkeypatch, _biz(booking_mode="external"), inserted=inserted)
    # If either of these is consulted in external mode, the test fails loudly.
    monkeypatch.setattr(
        cs.booking_service, "is_slot_available",
        lambda *a, **k: pytest.fail("external mode must not check our calendar"),
    )
    monkeypatch.setattr(
        cs.booking_service, "reserve_slot",
        lambda *a, **k: pytest.fail("external mode must not reserve a slot"),
    )

    out = cs._create_appointment_from_booking(_booking(), client_id_override="hm-olympia")
    assert out is not None
    assert inserted[0]["status"] == "pending_review"
    assert inserted[0]["source"] == "receptionist"


def test_external_request_survives_an_already_taken_slot(monkeypatch):
    """Zenoti owns availability, so our own booked_slots must not block a request."""
    inserted = []
    cs = _patch_common(monkeypatch, _biz(booking_mode="external"), inserted=inserted)
    monkeypatch.setattr(cs.booking_service, "is_slot_available", lambda *a, **k: False)
    monkeypatch.setattr(cs.booking_service, "reserve_slot", lambda *a, **k: False)

    out = cs._create_appointment_from_booking(_booking(), client_id_override="hm-olympia")
    assert out is not None, "a request must not be rejected by our own slot table"
    assert inserted[0]["status"] == "pending_review"


# --- Isolation: internal stores are untouched ---------------------------------


def test_internal_store_still_checks_and_reserves(monkeypatch):
    """The regression guard for every other customer: default mode keeps the full
    slot-check + reserve + pending_customer flow."""
    inserted = []
    cs = _patch_common(monkeypatch, _biz(), inserted=inserted)  # no booking_mode -> internal
    checked, reserved = [], []
    monkeypatch.setattr(
        cs.booking_service, "is_slot_available",
        lambda *a, **k: (checked.append(a), True)[1],
    )
    monkeypatch.setattr(
        cs.booking_service, "reserve_slot",
        lambda *a, **k: (reserved.append(a), True)[1],
    )
    monkeypatch.setattr(cs, "_supersede_pending_customer_drafts_for_slot", lambda *a, **k: None)

    out = cs._create_appointment_from_booking(
        _booking(), client_id_override="normal-shop", reserve_slot_immediately=True
    )
    assert out is not None
    assert checked, "internal mode must still check availability"
    assert reserved, "internal mode must still reserve the slot"
    assert inserted[0]["status"] == "pending_customer"


def test_internal_store_still_rejects_a_taken_slot(monkeypatch):
    """Double-booking protection must remain intact for internal stores."""
    inserted = []
    cs = _patch_common(monkeypatch, _biz(), inserted=inserted)
    monkeypatch.setattr(cs.booking_service, "is_slot_available", lambda *a, **k: False)
    monkeypatch.setattr(cs.booking_service, "_invalidate_booked_slots_cache", lambda: None)
    monkeypatch.setattr(cs.booking_service, "_slot_blocking_details", lambda *a, **k: {})
    monkeypatch.setattr(cs, "_supersede_pending_customer_drafts_for_slot", lambda *a, **k: None)

    out = cs._create_appointment_from_booking(_booking(), client_id_override="normal-shop")
    assert out is None, "internal mode must still refuse an already-booked slot"
    assert inserted == []
