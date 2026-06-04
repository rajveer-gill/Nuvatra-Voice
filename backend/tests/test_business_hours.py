"""After-hours detection for same-day booking."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from business_hours import (
    after_hours_prompt_block,
    is_past_closing_for_date,
    parse_hours_to_weekly,
    same_day_after_hours_message,
)


def test_parse_hours_mon_fri():
    sched = parse_hours_to_weekly("Monday-Friday: 9 AM - 5 PM")
    assert not sched[0].closed
    assert sched[0].open == "09:00"
    assert sched[0].close == "17:00"
    assert sched[5].closed


def test_after_hours_blocks_same_day_booking():
    info = {
        "name": "Test Salon",
        "hours": "Monday-Friday: 9 AM - 5 PM",
        "timezone": "America/Los_Angeles",
    }
    today = date(2026, 6, 4)  # Thursday
    now = datetime(2026, 6, 4, 18, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert is_past_closing_for_date(info, today, now) is True


def test_before_close_allows_same_day():
    info = {
        "hours": "Monday-Friday: 9 AM - 5 PM",
        "timezone": "America/Los_Angeles",
    }
    today = date(2026, 6, 4)
    now = datetime(2026, 6, 4, 14, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert is_past_closing_for_date(info, today, now) is False


def test_future_day_not_after_hours():
    info = {"hours": "Monday-Friday: 9 AM - 5 PM", "timezone": "America/Los_Angeles"}
    tomorrow = date(2026, 6, 5)
    now = datetime(2026, 6, 4, 20, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert is_past_closing_for_date(info, tomorrow, now) is False


def test_after_hours_prompt_block():
    info = {
        "name": "Test",
        "hours": "Monday-Friday: 9 AM - 5 PM",
        "timezone": "America/Los_Angeles",
    }
    now = datetime(2026, 6, 4, 18, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    block = after_hours_prompt_block(info, now)
    assert block is not None
    assert "AFTER HOURS" in block
    assert "closed for today" in block.lower() or "TODAY" in block


def test_same_day_message():
    msg = same_day_after_hours_message({"name": "Test Spa"})
    assert "closed for today" in msg.lower()
    assert "another day" in msg.lower()
