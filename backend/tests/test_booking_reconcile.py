"""Unit tests for the end-of-call booking reconciliation safety net.

reconcile_booking_at_call_end() runs when a call ends with no appointment created but the
transcript shows the caller agreed to a booking (e.g. the model never emitted the BOOKING:
marker, or the caller hung up mid-turn). It must:
  - create the appointment + send the confirmation SMS when the booking validates, and
  - NEVER book past the stylist/shop schedule backstop (e.g. a stylist on a day off).
"""
import conversation_service as cs


def _agreed_history():
    return [
        {"role": "user", "content": "I'd like to book a haircut with Mia"},
        {"role": "assistant", "content": "Sure, what day works?"},
        {"role": "user", "content": "Monday at 10 please"},
    ]


def _patch_common(monkeypatch):
    monkeypatch.setattr(
        cs.config_service,
        "get_business_info",
        lambda: {
            "staff": [{"id": "s1", "name": "Mia", "working_days": ["mon", "wed", "fri"]}],
            "services": [{"id": "svc1", "name": "Cut"}],
        },
    )
    monkeypatch.setattr(
        cs.config_service, "staff_roster_ready_for_booking", lambda *a, **k: True
    )
    monkeypatch.setattr(cs.database, "set_request_client_id", lambda *a, **k: None)


def test_reconcile_books_and_texts_valid_agreed_booking(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        cs,
        "_extract_booking_line_from_conversation",
        lambda *a, **k: {"name": "Sam", "date": "2026-07-06", "time": "10:00", "reason": "Cut", "staff": "Mia"},
    )
    monkeypatch.setattr(
        cs,
        "_validate_booking_requirements",
        lambda booking, conversation_history=None: (True, None, "s1", "Cut"),
    )
    calls = {}

    def _fake_create(booking, **k):
        calls["created"] = True
        return {"id": 42, "name": "Sam", "date": "2026-07-06", "time": "10:00", "reason": "Cut", "phone": "+15551234567"}

    monkeypatch.setattr(cs, "_create_appointment_from_booking", _fake_create)

    def _fake_sms(apt, call_data, cid, call_sid):
        calls["sms_apt_id"] = apt.get("id")
        return "texted"

    monkeypatch.setattr(cs, "_send_booking_confirmation_sms", _fake_sms)

    call_data = {
        "client_id": "test",
        "from_number": "+15551234567",
        "conversation_history": _agreed_history(),
    }
    assert cs.reconcile_booking_at_call_end(call_data, "CA1") is True
    assert call_data["appointment_created"] is True
    assert calls.get("created") is True
    assert calls.get("sms_apt_id") == 42


def test_reconcile_refuses_off_day_and_does_not_book(monkeypatch):
    _patch_common(monkeypatch)
    # Caller agreed to Thursday with Mia, who only works Mon/Wed/Fri: the backstop rejects it.
    monkeypatch.setattr(
        cs,
        "_extract_booking_line_from_conversation",
        lambda *a, **k: {"name": "Sam", "date": "2026-07-09", "time": "10:00", "reason": "Cut", "staff": "Mia"},
    )
    monkeypatch.setattr(
        cs,
        "_validate_booking_requirements",
        lambda booking, conversation_history=None: (False, "Mia doesn't work on Thursday.", "s1", "Cut"),
    )

    def _must_not_create(*a, **k):
        raise AssertionError("must not create an appointment for an off-day booking")

    def _must_not_sms(*a, **k):
        raise AssertionError("must not send a confirmation SMS when rejected")

    monkeypatch.setattr(cs, "_create_appointment_from_booking", _must_not_create)
    monkeypatch.setattr(cs, "_send_booking_confirmation_sms", _must_not_sms)

    call_data = {
        "client_id": "test",
        "from_number": "+15551234567",
        "conversation_history": _agreed_history(),
    }
    assert cs.reconcile_booking_at_call_end(call_data, "CA2") is False
    assert not call_data.get("appointment_created")


def test_reconcile_noop_when_no_booking_extracted(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(cs, "_extract_booking_line_from_conversation", lambda *a, **k: None)

    def _must_not_create(*a, **k):
        raise AssertionError("must not create when nothing was extracted")

    monkeypatch.setattr(cs, "_create_appointment_from_booking", _must_not_create)

    call_data = {
        "client_id": "test",
        "from_number": "+15551234567",
        "conversation_history": _agreed_history(),
    }
    assert cs.reconcile_booking_at_call_end(call_data, "CA3") is False


def test_reconcile_noop_when_conversation_not_a_booking(monkeypatch):
    _patch_common(monkeypatch)

    def _must_not_extract(*a, **k):
        raise AssertionError("must not extract when the conversation isn't a booking")

    monkeypatch.setattr(cs, "_extract_booking_line_from_conversation", _must_not_extract)

    call_data = {
        "client_id": "test",
        "from_number": "+15551234567",
        "conversation_history": [{"role": "user", "content": "What are your hours today?"}],
    }
    assert cs.reconcile_booking_at_call_end(call_data, "CA4") is False


def test_reconcile_noop_when_already_booked(monkeypatch):
    def _must_not_extract(*a, **k):
        raise AssertionError("must not run when an appointment already exists")

    monkeypatch.setattr(cs, "_extract_booking_line_from_conversation", _must_not_extract)

    call_data = {
        "appointment_created": True,
        "conversation_history": _agreed_history(),
    }
    assert cs.reconcile_booking_at_call_end(call_data, "CA5") is False


def _change_wire(monkeypatch, *, existing, extracted):
    _patch_common(monkeypatch)
    monkeypatch.setattr(cs.runtime, "USE_DB", True)
    monkeypatch.setattr(
        cs.database, "db_appointments_get_pending_by_phone",
        lambda phone: (dict(existing) if existing else None),
    )
    monkeypatch.setattr(
        cs, "_extract_booking_line_from_conversation",
        lambda *a, **k: (dict(extracted) if extracted else None),
    )
    monkeypatch.setattr(
        cs, "_validate_booking_requirements",
        lambda booking, conversation_history=None: (True, None, "s1", "Cut"),
    )
    calls = {}

    def _fake_create(booking, **k):
        calls["created"] = dict(booking)
        return {"id": 6, "date": booking.get("date"), "time": booking.get("time"), "reason": booking.get("reason"), "phone": "+15551234567"}

    monkeypatch.setattr(cs, "_create_appointment_from_booking", _fake_create)
    monkeypatch.setattr(cs, "_send_booking_confirmation_sms", lambda *a, **k: calls.__setitem__("texted", True))
    cancels = []
    monkeypatch.setattr(cs.database, "db_appointments_update", lambda aid, **k: cancels.append((aid, k)))
    monkeypatch.setattr(cs.booking_service, "release_slot", lambda aid: None)
    return calls, cancels


def _change_call_data():
    return {
        "appointment_created": True,
        "client_id": "test",
        "from_number": "+15551234567",
        "conversation_history": _agreed_history(),
    }


def test_reconcile_applies_mid_call_change(monkeypatch):
    # The model narrated "let's do the 8th" without a marker; the change must still apply.
    calls, cancels = _change_wire(
        monkeypatch,
        existing={"id": 5, "status": "pending_customer", "date": "2026-07-06", "time": "14:00", "reason": "Cut", "staff_id": "s1"},
        extracted={"name": "Sam", "date": "2026-07-08", "time": "10:00", "reason": "Cut", "staff": "Mia"},
    )
    assert cs.reconcile_booking_at_call_end(_change_call_data(), "CA1") is True
    assert calls.get("created", {}).get("date") == "2026-07-08"  # new details applied
    assert calls.get("texted")  # updated confirmation sent
    assert any(k.get("status") == "cancelled" for _, k in cancels)  # old draft cancelled (no dup)


def test_reconcile_change_noop_when_nothing_changed(monkeypatch):
    calls, _ = _change_wire(
        monkeypatch,
        existing={"id": 5, "status": "pending_customer", "date": "2026-07-06", "time": "14:00", "reason": "Cut", "staff_id": "s1"},
        extracted={"name": "Sam", "date": "2026-07-06", "time": "14:00", "reason": "Cut", "staff": "Mia"},
    )
    assert cs.reconcile_booking_at_call_end(_change_call_data(), "CA2") is False
    assert "created" not in calls  # don't re-text when nothing changed


def test_reconcile_change_skips_confirmed_appointment(monkeypatch):
    calls, _ = _change_wire(
        monkeypatch,
        existing={"id": 5, "status": "pending_review", "date": "2026-07-06", "time": "14:00", "reason": "Cut", "staff_id": "s1"},
        extracted={"name": "Sam", "date": "2026-07-08", "time": "10:00", "reason": "Cut", "staff": "Mia"},
    )
    assert cs.reconcile_booking_at_call_end(_change_call_data(), "CA3") is False
    assert "created" not in calls  # never rewrite an already-confirmed booking
