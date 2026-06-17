"""Vertical terminology: the receptionist's wording follows business_vertical.

salon_chair must keep saying "stylist"/"salon" (back-compat with existing tests);
auto_body must say "technician" and never "stylist".
"""

import booking_service
import config_service
import verticals
from prompts.receptionist import appointment_focus_guidance, build_system_prompt


# ---- registry ----

def test_registry_supports_salon_and_auto_body():
    assert verticals.is_supported("salon_chair")
    assert verticals.is_supported("auto_body")
    assert not verticals.is_supported("nope")
    assert "salon_chair" in verticals.allowed_verticals()
    assert "auto_body" in verticals.allowed_verticals()


def test_terms_for_falls_back_to_default():
    assert verticals.terms_for(None).provider == "stylist"
    assert verticals.terms_for("unknown").provider == "stylist"
    assert verticals.terms_for("auto_body").provider == "technician"


def test_config_service_allowed_verticals_comes_from_registry():
    assert config_service.ALLOWED_BUSINESS_VERTICALS == verticals.allowed_verticals()
    assert "auto_body" in config_service.BUSINESS_VERTICAL_LABELS


def test_vertical_choices_shape():
    choices = verticals.vertical_choices()
    assert {"value", "label"} <= set(choices[0].keys())
    assert any(c["value"] == "auto_body" for c in choices)


# ---- voice prompt ----

def _biz(vertical):
    return {
        "name": "Test Shop",
        "business_vertical": vertical,
        "services": [{"id": "s1", "name": "Estimate", "price": 0, "duration_minutes": 30}],
        "staff": [{"name": "Jamie"}, {"name": "Alex"}],
    }


def test_salon_prompt_says_stylist():
    p = build_system_prompt(
        business_info=_biz("salon_chair"), include_booked_slots=True, booked_slots_prompt_text=""
    )
    assert "stylist" in p
    assert "technician" not in p


def test_auto_body_prompt_says_technician_not_stylist():
    p = build_system_prompt(
        business_info=_biz("auto_body"), include_booked_slots=True, booked_slots_prompt_text=""
    )
    assert "technician" in p
    assert "stylist" not in p
    # The provider section header follows the vertical too.
    assert "TECHNICIAN: Multiple team members" in p


def test_unknown_vertical_prompt_defaults_to_salon_wording():
    p = build_system_prompt(
        business_info=_biz("totally_new"), include_booked_slots=True, booked_slots_prompt_text=""
    )
    assert "stylist" in p


def test_focus_guidance_provider_param():
    g = appointment_focus_guidance("Test Shop", include_booked_slots=True, provider="technician")
    assert "technician" in g
    assert "stylist" not in g


# ---- vertical-specific booking intake ----

def test_auto_body_prompt_gathers_vehicle_and_insurance():
    p = build_system_prompt(
        business_info=_biz("auto_body"), include_booked_slots=True, booked_slots_prompt_text=""
    )
    # The auto body intake asks for the things a body shop actually needs.
    assert "AUTO BODY INTAKE" in p
    assert "VEHICLE" in p
    assert "INSURANCE" in p
    assert "DRIVABLE" in p


def test_salon_prompt_has_no_auto_body_intake():
    p = build_system_prompt(
        business_info=_biz("salon_chair"), include_booked_slots=True, booked_slots_prompt_text=""
    )
    assert "AUTO BODY INTAKE" not in p
    assert "VEHICLE" not in p


def test_registry_exposes_intake_and_examples():
    assert verticals.terms_for("auto_body").intake_guidance
    assert "Collision" in verticals.terms_for("auto_body").service_examples
    # Salon has no extra intake (keeps its prompt unchanged).
    assert verticals.terms_for("salon_chair").intake_guidance == ""


# ---- structured intake capture ----

def test_intake_field_dicts():
    fields = verticals.intake_field_dicts("auto_body")
    assert {"key": "vehicle", "label": "Vehicle"} in fields
    assert any(f["key"] == "insurance" for f in fields)
    # Salon has no structured intake.
    assert verticals.intake_field_dicts("salon_chair") == []


def test_extract_intake_none_for_vertical_without_fields(monkeypatch):
    import conversation_service as cs

    monkeypatch.setattr(
        cs.config_service, "get_business_info", lambda: {"business_vertical": "salon_chair"}
    )
    # No GPT call should be needed; salon has no intake fields.
    assert cs._extract_intake_from_conversation([{"role": "user", "content": "hi"}]) is None


def test_extract_intake_parses_auto_body(monkeypatch):
    import conversation_service as cs
    from types import SimpleNamespace

    monkeypatch.setattr(
        cs.config_service, "get_business_info", lambda: {"business_vertical": "auto_body"}
    )

    def fake_create(**kwargs):
        content = '{"vehicle": "2019 Honda Civic", "insurance": "Geico claim", "damage": "rear bumper", "drivable": "yes"}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(
        cs.runtime,
        "client",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
    )
    out = cs._extract_intake_from_conversation(
        [{"role": "user", "content": "2019 honda civic, geico, rear bumper, drives fine"}]
    )
    assert out["vehicle"] == "2019 Honda Civic"
    assert out["insurance"] == "Geico claim"
    assert out["drivable"] == "yes"


def test_appointment_intake_json_round_trips_to_dict():
    # _coerce_intake handles both dict (psycopg2 default) and JSON-string forms.
    import database
    assert database._coerce_intake({"vehicle": "Civic"}) == {"vehicle": "Civic"}
    assert database._coerce_intake('{"vehicle": "Civic"}') == {"vehicle": "Civic"}
    assert database._coerce_intake(None) is None
    assert database._coerce_intake("") is None


# ---- SMS confirmation label ----

def _apt():
    return {
        "name": "Casey",
        "phone": "+15551234567",
        "date": "2026-07-01",
        "time": "10:00",
        "reason": "Estimate",
        "status": "pending_customer",
        "staff_id": "s1",
    }


def test_confirmation_sms_label_follows_vertical(monkeypatch):
    monkeypatch.setattr(
        config_service,
        "get_business_info",
        lambda: {"business_vertical": "auto_body", "staff": [{"id": "s1", "name": "Jamie"}]},
    )
    msg = booking_service._format_appointment_details_confirmation_sms(_apt())
    assert "Technician: Jamie" in msg
    assert "Stylist:" not in msg


def test_confirmation_sms_label_defaults_to_stylist(monkeypatch):
    monkeypatch.setattr(
        config_service,
        "get_business_info",
        lambda: {"staff": [{"id": "s1", "name": "Jamie"}]},
    )
    msg = booking_service._format_appointment_details_confirmation_sms(_apt())
    assert "Stylist: Jamie" in msg
