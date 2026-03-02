"""Unit tests for parse_booking."""
import pytest
from main import parse_booking


def test_parse_booking_valid():
    text = "BOOKING: John Doe|+15551234567|john@example.com|2025-03-15|10:30|Haircut"
    got = parse_booking(text)
    assert got is not None
    assert got["name"] == "John Doe"
    assert got["phone"] == "+15551234567"
    assert got["email"] == "john@example.com"
    assert got["date"] == "2025-03-15"
    assert got["time"] == "10:30"
    assert got["reason"] == "Haircut"


def test_parse_booking_minimal():
    text = "BOOKING: Jane|5551234567| |2025-03-20|14:00|Color"
    got = parse_booking(text)
    assert got is not None
    assert got["name"] == "Jane"
    assert got["date"] == "2025-03-20"
    assert got["time"] == "14:00"


def test_parse_booking_empty():
    assert parse_booking("") is None
    assert parse_booking(None) is None


def test_parse_booking_no_booking_marker():
    assert parse_booking("Just some text") is None
    assert parse_booking("Thanks for calling!") is None


def test_parse_booking_too_few_fields():
    text = "BOOKING: John|555"
    got = parse_booking(text)
    assert got is None
