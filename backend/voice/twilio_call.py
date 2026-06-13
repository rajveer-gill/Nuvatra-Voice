"""Safe Twilio REST call updates from async voice handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from observability import voice_info, voice_warning

_log = logging.getLogger("nuvatra")

try:
    from twilio.base.exceptions import TwilioRestException
except ImportError:  # pragma: no cover
    TwilioRestException = Exception  # type: ignore[misc, assignment]


def _call_not_updatable(exc: BaseException) -> bool:
    if not isinstance(exc, TwilioRestException):
        return False
    msg = str(exc).lower()
    return exc.status == 400 and ("not in-progress" in msg or "cannot redirect" in msg)


async def safe_twilio_call_update(
    twilio_client: Any,
    call_sid: str,
    twiml: str,
    *,
    op: str,
    require_active_session: bool = True,
) -> bool:
    """
    Replace in-progress call TwiML. Returns False if the call already ended or session is gone
    (expected race when caller hangs up during Media Streams).
    """
    if require_active_session:
        import runtime

        if not runtime.call_store.exists(call_sid):
            voice_info(
                "twilio_calls_update_skipped",
                call_sid=call_sid,
                reason="session_gone",
                op=op,
            )
            return False
    try:
        await asyncio.to_thread(twilio_client.calls(call_sid).update, twiml=twiml)
        voice_info("twilio_calls_update_ok", call_sid=call_sid, op=op)
        return True
    except Exception as e:
        if _call_not_updatable(e):
            voice_info(
                "twilio_calls_update_skipped",
                call_sid=call_sid,
                reason="call_not_in_progress",
                op=op,
            )
            return False
        voice_warning(
            "twilio_calls_update_failed",
            call_sid=call_sid,
            op=op,
            error_type=type(e).__name__,
        )
        _log.exception("twilio_calls_update_failed call_sid=%s op=%s", call_sid, op)
        return False
