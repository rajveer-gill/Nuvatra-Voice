"""Consistent masking of phone numbers and tokens for logs."""

from __future__ import annotations


def mask_phone_e164(phone: str | None, *, keep_start: int = 6, keep_end: int = 2) -> str:
    """Mask E.164-ish phone for logs (e.g. +1555123...89)."""
    if not phone:
        return "(empty)"
    p = "".join(c for c in phone if c.isdigit() or c == "+")
    if len(p) < 8:
        return "***"
    # strip + for length check
    digits = "".join(c for c in p if c.isdigit())
    if len(digits) < 8:
        return "***"
    return f"{p[:keep_start]}...{p[-keep_end:]}" if len(p) >= keep_start + keep_end else "***"
