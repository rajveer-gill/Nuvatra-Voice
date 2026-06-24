"""Per-stylist working days / hours: normalization, prompt text, and booking backstop."""

import staff_schedule as ss

# 2026-06-26 is a Friday; 2026-06-22 is a Monday.
FRIDAY = "2026-06-26"
MONDAY = "2026-06-22"


def test_normalize_working_days():
    assert ss.normalize_working_days(["Friday", "mon", "MON", "xyz", "tue"]) == ["mon", "tue", "fri"]
    assert ss.normalize_working_days([]) == []
    assert ss.normalize_working_days("fri") == ["fri"]


def test_normalize_working_hours_drops_invalid():
    out = ss.normalize_working_hours(
        {
            "fri": {"start": "12:00", "end": "17:00"},
            "xyz": {"start": "09:00", "end": "17:00"},  # invalid day
            "mon": {"start": "09:00", "end": "09:00"},  # start == end
            "tue": {"start": "bad", "end": "17:00"},  # invalid time
        }
    )
    assert out == {"fri": {"start": "12:00", "end": "17:00"}}


def test_unavailable_on_off_day():
    row = {"name": "Jake", "working_days": ["mon", "tue", "wed", "thu"]}
    msg = ss.staff_unavailable_message(row, FRIDAY, "14:00")
    assert msg and "Jake" in msg and "Friday" in msg


def test_available_on_working_day():
    row = {"name": "Jake", "working_days": ["mon", "tue", "wed", "thu", "fri"]}
    assert ss.staff_unavailable_message(row, FRIDAY, "14:00") is None


def test_outside_working_hours_rejected_within_accepted():
    row = {"name": "Jake", "working_days": ["fri"], "working_hours": {"fri": {"start": "12:00", "end": "17:00"}}}
    msg = ss.staff_unavailable_message(row, FRIDAY, "10:00")
    assert msg and "Friday" in msg
    assert ss.staff_unavailable_message(row, FRIDAY, "13:00") is None


def test_no_constraint_when_unset():
    assert ss.staff_unavailable_message({"name": "Jake"}, FRIDAY, "14:00") is None


def test_prompt_text_includes_days_and_hours():
    row = {"working_days": ["mon", "fri"], "working_hours": {"fri": {"start": "12:00", "end": "17:00"}}}
    txt = ss.working_days_prompt_text(row)
    assert "Monday, Friday" in txt
    assert "Friday 12:00 PM" in txt and "5:00 PM" in txt
    assert ss.working_days_prompt_text({}) == ""
