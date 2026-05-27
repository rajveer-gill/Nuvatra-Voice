"""Unit tests for SMS appointment detail parsing."""

from sms_appointment_updates import (
    apply_sms_appointment_detail_updates,
    parse_email_from_sms,
    parse_name_from_sms,
)


def test_parse_name_correction_not_jake():
    assert parse_name_from_sms("my name is Raj, not jake and my email is x@y.com", current_name="Jake") == "Raj"


def test_parse_email():
    assert parse_email_from_sms("my email is rajgill1abc@gmail.com") == "rajgill1abc@gmail.com"


def test_parse_name_unchanged_returns_none():
    assert parse_name_from_sms("my name is Jake", current_name="Jake") is None


def test_apply_updates_name_and_email():
    stored = {"id": 1, "status": "pending_customer", "name": "Jake", "email": ""}
    updates_log = []

    def fake_update(aid, client_id, **kwargs):
        stored.update(kwargs)
        updates_log.append(kwargs)
        return dict(stored)

    def fake_get(aid, client_id):
        return dict(stored)

    mem = []

    def fake_memory(phone, name=None, increment_count=False, data_patch=None):
        mem.append({"name": name, "data_patch": data_patch})

    out, changed = apply_sms_appointment_detail_updates(
        "my name is Raj, not jake and rajgill1abc@gmail.com",
        stored,
        client_id="test",
        from_number="+15551234567",
        db_appointments_update=fake_update,
        db_appointments_get_by_id=fake_get,
        update_caller_memory=fake_memory,
        system_info=lambda *a, **k: None,
        logger=__import__("logging").getLogger("test"),
    )
    assert out["name"] == "Raj"
    assert out["email"] == "rajgill1abc@gmail.com"
    assert set(changed) == {"name", "email"}
    assert "name" in updates_log[0]
    assert "email" in updates_log[0]


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

    out, changed = apply_sms_appointment_detail_updates_from_bodies(
        ["my name is Raj and my email is raj@example.com"],
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
    assert out["email"] == "raj@example.com"
    assert set(changed) == {"name", "email"}


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
    assert "2:00 PM" in msg
    assert "YES or CONFIRM" in msg
