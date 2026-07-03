"""Unit tests for SMS appointment detail parsing."""

from sms_appointment_updates import (
    apply_sms_appointment_detail_updates,
    parse_email_from_sms,
    parse_name_from_sms,
    parse_service_from_sms,
    parse_time_from_sms,
    normalize_time_to_hhmm,
)

_MENU = ["Short Cut", "Long Cut", "Fade", "Beard Trim"]


def test_parse_service_natural_phrasing_matches_menu():
    # Regression: a text like this returned no match because the parser required the literal
    # word "service" — so a customer's SMS service change never reached the dashboard.
    assert parse_service_from_sms("make it a long cut", current_service="Short Cut", known_services=_MENU) == "Long Cut"
    assert parse_service_from_sms("can I change to a fade instead", current_service="Short Cut", known_services=_MENU) == "Fade"


def test_parse_service_longest_menu_name_wins():
    assert parse_service_from_sms("i'd like a long cut", current_service="Fade", known_services=_MENU) == "Long Cut"


def test_parse_service_same_as_current_returns_none():
    assert parse_service_from_sms("long cut is good", current_service="Long Cut", known_services=_MENU) is None


def test_parse_service_pure_confirmation_returns_none():
    assert parse_service_from_sms("yes", current_service="Fade", known_services=_MENU) is None


def test_parse_service_regex_fallback_without_menu():
    # Back-compat: the rigid pattern still works when no menu is supplied.
    assert parse_service_from_sms("change service to Balayage") == "Balayage"


def test_parse_name_correction_not_jake():
    assert parse_name_from_sms("my name is Raj, not jake and my email is x@y.com", current_name="Jake") == "Raj"


def test_parse_email():
    assert parse_email_from_sms("my email is rajgill1abc@gmail.com") == "rajgill1abc@gmail.com"


def test_parse_name_unchanged_returns_none():
    assert parse_name_from_sms("my name is Jake", current_name="Jake") is None


def test_parse_time_can_we_do_3():
    assert parse_time_from_sms("can we do 3 actually?", current_time="14:00") == "15:00"


def test_parse_time_unchanged_returns_none():
    assert parse_time_from_sms("can we do 2?", current_time="14:00") is None


def test_parse_time_skips_confirmation_only():
    assert parse_time_from_sms("yup! thats correct", current_time="14:00") is None


def test_apply_time_change_from_bodies():
    stored = {
        "id": 2,
        "status": "pending_customer",
        "name": "Raj",
        "date": "2026-06-05",
        "time": "14:00",
        "reason": "Long Cut",
    }

    def fake_update(aid, client_id, **kwargs):
        stored.update(kwargs)
        return dict(stored)

    from sms_appointment_updates import apply_sms_appointment_detail_updates_from_bodies

    out, changed = apply_sms_appointment_detail_updates_from_bodies(
        ["can we do 3 actually?"],
        stored,
        client_id="test",
        from_number="+15551234567",
        db_appointments_update=fake_update,
        db_appointments_get_by_id=lambda aid, client_id: dict(stored),
        update_caller_memory=lambda *a, **k: None,
        system_info=lambda *a, **k: None,
        logger=__import__("logging").getLogger("test"),
    )
    assert out["time"] == "15:00"
    assert changed == ["time"]


def test_apply_time_change_on_confirm_turn_reads_prior_body():
    stored = {
        "id": 3,
        "status": "pending_customer",
        "name": "Raj",
        "date": "2026-06-05",
        "time": "14:00",
        "reason": "Long Cut",
    }

    def fake_update(aid, client_id, **kwargs):
        stored.update(kwargs)
        return dict(stored)

    from sms_appointment_updates import apply_sms_appointment_detail_updates_from_bodies

    out, changed = apply_sms_appointment_detail_updates_from_bodies(
        ["can we do 3 actually?", "yup! thats correct"],
        stored,
        client_id="test",
        from_number="+15551234567",
        db_appointments_update=fake_update,
        db_appointments_get_by_id=lambda aid, client_id: dict(stored),
        update_caller_memory=lambda *a, **k: None,
        system_info=lambda *a, **k: None,
        logger=__import__("logging").getLogger("test"),
    )
    assert out["time"] == "15:00"
    assert changed == ["time"]
    assert normalize_time_to_hhmm(out["time"]) == "15:00"


def test_apply_updates_name_only_ignores_email_in_sms():
    stored = {"id": 1, "status": "pending_customer", "name": "Jake", "email": ""}
    updates_log = []

    def fake_update(aid, client_id, **kwargs):
        stored.update(kwargs)
        updates_log.append(kwargs)
        return dict(stored)

    def fake_get(aid, client_id):
        return dict(stored)

    out, changed = apply_sms_appointment_detail_updates(
        "my name is Raj, not jake and rajgill1abc@gmail.com",
        stored,
        client_id="test",
        from_number="+15551234567",
        db_appointments_update=fake_update,
        db_appointments_get_by_id=fake_get,
        update_caller_memory=lambda *a, **k: None,
        system_info=lambda *a, **k: None,
        logger=__import__("logging").getLogger("test"),
    )
    assert out["name"] == "Raj"
    assert out["email"] == ""
    assert changed == ["name"]


def test_apply_from_bodies_name_on_prior_turn_confirm_yes():
    stored = {"id": 1, "status": "pending_customer", "name": "Jake", "email": ""}

    def fake_update(aid, client_id, **kwargs):
        stored.update(kwargs)
        return dict(stored)

    from sms_appointment_updates import apply_sms_appointment_detail_updates_from_bodies

    out, changed_first = apply_sms_appointment_detail_updates_from_bodies(
        ["my name is Raj, not jake"],
        stored,
        client_id="test",
        from_number="+15551234567",
        db_appointments_update=fake_update,
        db_appointments_get_by_id=lambda aid, client_id: dict(stored),
        update_caller_memory=lambda *a, **k: None,
        system_info=lambda *a, **k: None,
        logger=__import__("logging").getLogger("test"),
    )
    assert out["name"] == "Raj"
    assert changed_first == ["name"]

    out2, changed_yes = apply_sms_appointment_detail_updates_from_bodies(
        ["my name is Raj, not jake", "Yes"],
        out,
        client_id="test",
        from_number="+15551234567",
        db_appointments_update=fake_update,
        db_appointments_get_by_id=lambda aid, client_id: dict(stored),
        update_caller_memory=lambda *a, **k: None,
        system_info=lambda *a, **k: None,
        logger=__import__("logging").getLogger("test"),
    )
    assert out2["name"] == "Raj"
    assert changed_yes == []


def test_apply_updates_name_for_accepted_appointment():
    stored = {"id": 9, "status": "accepted", "name": "Jake", "email": "old@example.com"}

    def fake_update(aid, client_id, **kwargs):
        stored.update(kwargs)
        return dict(stored)

    from sms_appointment_updates import apply_sms_appointment_detail_updates_from_bodies

    bulk_calls = []

    out, changed = apply_sms_appointment_detail_updates_from_bodies(
        ["my name is Raj and my email is raj@example.com"],
        stored,
        client_id="test",
        from_number="+15551234567",
        db_appointments_update=fake_update,
        db_appointments_get_by_id=lambda aid, client_id: dict(stored),
        update_caller_memory=lambda *a, **k: None,
        db_appointments_update_active_name_by_phone=lambda phone, client_id, name, exclude_appointment_id=None: bulk_calls.append((phone, name, exclude_appointment_id)) or 1,
        system_info=lambda *a, **k: None,
        logger=__import__("logging").getLogger("test"),
    )
    assert out["name"] == "Raj"
    assert out["email"] == "old@example.com"
    assert changed == ["name"]
    assert bulk_calls and bulk_calls[0][1] == "Raj"


def test_format_appointment_details_confirmation_sms():
    from main import _format_appointment_details_confirmation_sms

    msg = _format_appointment_details_confirmation_sms(
        {
            "name": "Raj",
            "phone": "+15551234567",
            "email": "r@test.com",
            "date": "2026-05-28",
            "time": "14:00",
            "reason": "Haircut",
            "status": "pending_customer",
        }
    )
    assert "Raj" in msg
    assert "Customer: Raj" in msg
    assert "2:00 PM" in msg
    assert "YES or CONFIRM" in msg
    assert "Email:" not in msg


# --- Stylist change over SMS -------------------------------------------------

import logging as _logging

from sms_appointment_updates import (
    apply_sms_appointment_detail_updates_from_bodies,
    parse_stylist_from_sms,
)

_ROSTER = ["Tom", "Andrew"]


def test_parse_stylist_switch_phrasing():
    assert parse_stylist_from_sms("can I switch to Andrew instead", current_stylist="Tom", known_stylists=_ROSTER) == "Andrew"
    assert parse_stylist_from_sms("actually with tom please", current_stylist="Andrew", known_stylists=_ROSTER) == "Tom"


def test_parse_stylist_same_as_current_returns_none():
    assert parse_stylist_from_sms("Andrew is great", current_stylist="Andrew", known_stylists=_ROSTER) is None


def test_parse_stylist_ignores_customer_own_name():
    # "my name is Andrew" is the customer identifying themselves, not a stylist switch.
    assert parse_stylist_from_sms("my name is Andrew", current_stylist="Tom", known_stylists=_ROSTER) is None


def _run_stylist_change(body, *, known_staff, service_id_by_name, stored):
    def fake_update(aid, client_id, **kwargs):
        stored.update(kwargs)
        return dict(stored)

    return apply_sms_appointment_detail_updates_from_bodies(
        [body],
        stored,
        client_id="test",
        from_number="+15551234567",
        db_appointments_update=fake_update,
        db_appointments_get_by_id=lambda aid, client_id: dict(stored),
        update_caller_memory=lambda *a, **k: None,
        system_info=lambda *a, **k: None,
        logger=_logging.getLogger("test"),
        known_staff=known_staff,
        service_id_by_name=service_id_by_name,
    )


def test_apply_stylist_change_updates_staff_id():
    stored = {"id": 10, "status": "pending_customer", "name": "Raj", "date": "2026-07-06", "time": "14:00", "reason": "Long Cut", "staff_id": "s1"}
    out, changed = _run_stylist_change(
        "can I switch to Andrew instead",
        known_staff=[{"id": "s1", "name": "Tom", "service_ids": []}, {"id": "s2", "name": "Andrew", "service_ids": []}],
        service_id_by_name={"long cut": "svc1"},
        stored=stored,
    )
    assert out["staff_id"] == "s2"


def test_apply_stylist_change_rejected_when_off_that_day():
    stored = {"id": 11, "status": "pending_customer", "name": "Raj", "date": "2026-07-06", "time": "14:00", "reason": "Long Cut", "staff_id": "s1"}
    out, changed = _run_stylist_change(
        "switch me to Andrew",
        # Andrew is on time off that exact date -> must not apply.
        known_staff=[{"id": "s1", "name": "Tom", "service_ids": []}, {"id": "s2", "name": "Andrew", "service_ids": [], "time_off": ["2026-07-06"]}],
        service_id_by_name={"long cut": "svc1"},
        stored=stored,
    )
    assert out.get("staff_id") == "s1"  # unchanged


def test_apply_stylist_change_rejected_when_service_not_offered():
    stored = {"id": 12, "status": "pending_customer", "name": "Raj", "date": "2026-07-06", "time": "14:00", "reason": "Long Cut", "staff_id": "s1"}
    out, changed = _run_stylist_change(
        "switch to Andrew",
        # Andrew only does svc2; the appointment's service (Long Cut) is svc1 -> must not apply.
        known_staff=[{"id": "s1", "name": "Tom", "service_ids": []}, {"id": "s2", "name": "Andrew", "service_ids": ["svc2"]}],
        service_id_by_name={"long cut": "svc1"},
        stored=stored,
    )
    assert out.get("staff_id") == "s1"  # unchanged
