"""Sanity checks for observability helpers."""
from observability import mask_phone


def test_mask_phone_masks_us_numbers():
    assert "..." in mask_phone("+15551234567")
    assert mask_phone("") == "(none)"


def test_mask_phone_short_input():
    assert mask_phone("123") == "***"
