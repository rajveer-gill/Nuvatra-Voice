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


# ----- specific-date time off / closures ------------------------------------

from datetime import date  # noqa: E402


def test_normalize_date_list_validates_dedupes_sorts_caps():
    assert ss.normalize_date_list(["2026-07-03", "bad", "2026-07-03", "2026-07-01"]) == [
        "2026-07-01",
        "2026-07-03",
    ]
    assert ss.normalize_date_list([]) == []
    assert ss.normalize_date_list("2026-07-01") == ["2026-07-01"]
    # cap: 400 valid consecutive dates → capped at MAX_DATES
    from datetime import timedelta

    base = date(2026, 1, 1)
    big = [(base + timedelta(days=i)).isoformat() for i in range(400)]
    assert len(ss.normalize_date_list(big)) == ss.MAX_DATES


def test_collapse_date_ranges():
    assert ss.collapse_date_ranges(["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-05"]) == [
        "Jul 1–3",
        "Jul 5",
    ]


def test_shop_closure_message():
    assert ss.shop_closure_message(["2026-07-04"], "2026-07-04")
    assert "closed" in ss.shop_closure_message(["2026-07-04"], "2026-07-04").lower()
    assert ss.shop_closure_message(["2026-07-04"], "2026-07-05") is None
    assert ss.shop_closure_message([], "2026-07-04") is None


def test_staff_time_off_blocks_booking():
    row = {"name": "Jake", "time_off": ["2026-07-03"]}
    msg = ss.staff_unavailable_message(row, "2026-07-03", "14:00")
    assert msg and "Jake" in msg and "off" in msg.lower()
    assert ss.staff_unavailable_message(row, "2026-07-04", "14:00") is None


def test_appointment_conflict_labels():
    assert ss.appointment_conflict(None, ["2026-07-04"], "2026-07-04") == {
        "type": "shop_closed",
        "label": "Shop closed",
    }
    assert ss.appointment_conflict({"name": "Jake", "time_off": ["2026-07-03"]}, [], "2026-07-03") == {
        "type": "stylist_off",
        "label": "Jake is off this day",
    }
    assert ss.appointment_conflict({"name": "Jake"}, [], "2026-07-03") is None


def test_upcoming_dates_filters_past_and_caps():
    today = date(2026, 7, 1)
    dates = ["2026-06-01", "2026-07-02", "2027-01-01"]  # past, soon, far
    out = ss.upcoming_dates(dates, today=today)
    assert "2026-07-02" in out
    assert "2026-06-01" not in out  # past dropped
    assert "2027-01-01" not in out  # beyond horizon
