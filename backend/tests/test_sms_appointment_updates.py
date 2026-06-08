"""Unit tests for SMS appointment detail parsing."""

from sms_appointment_updates import (
    apply_sms_appointment_detail_updates,
    parse_email_from_sms,
    parse_name_from_sms,
    parse_time_from_sms,
    normalize_time_to_hhmm,
)


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
