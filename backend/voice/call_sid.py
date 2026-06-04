"""Twilio CallSid validation for runtime state keys."""

from __future__ import annotations

import re

# Twilio Call SIDs: CA + 32 hex chars (case-insensitive).
_CALL_SID_RE = re.compile(r"^CA[a-fA-F0-9]{32}$")

# Valid example for unit tests (not a real Twilio resource).
SAMPLE_CALL_SID = "CAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def normalize_call_sid(call_sid: str | None) -> str:
    """Return stripped CallSid or empty string if invalid."""
    if not isinstance(call_sid, str):
        return ""
    sid = call_sid.strip()
    if not sid or not _CALL_SID_RE.fullmatch(sid):
        return ""
    return sid


def is_valid_call_sid(call_sid: str | None) -> bool:
    return bool(normalize_call_sid(call_sid))
