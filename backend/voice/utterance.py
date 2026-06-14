"""Shared caller transcript → GPT/Twilio pipeline (Gather and Deepgram paths)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import quote

import runtime  # the live call-session store singleton lives here (not on main)
from observability import voice_call_phase, voice_debug, voice_forward, voice_info, voice_warning
from voice.call_session_store import UtteranceLockError
from voice.stt_runtime import deepgram_stt_active
from voice.twiml_stt import empty_retry_twiml

_log = logging.getLogger("nuvatra")

# Hard ceilings for a single call so a runaway/abusive/looping caller can't run up
# unbounded OpenAI + Twilio cost. These bound one call; account-level usage is alert-only.
MAX_CALL_SECONDS = 600  # ~10 minutes of wall-clock
MAX_USER_TURNS = 25     # caller speaking turns


@dataclass
class UtteranceResult:
    """
    tail_play_respond: schedule GPT+TTS; Twilio should play got-it + redirect to respond
      (HTTP path returns that TwiML; Connect+Stream path already queued it after </Connect>).
    replace_call_twiml: Twilio REST must replace current TwiML (forward / Record / lost session).
    """

    mode: Literal["tail_play_respond", "replace_call_twiml"]
    replacement_twiml: Optional[str] = None


async def apply_caller_utterance(
    call_sid: str,
    speech_result: str,
    confidence: float,
    base_url: str,
) -> UtteranceResult:
    """Mirror `process_speech` core logic without reading Twilio form bodies."""
    import main as m

    voice_debug(
        "utterance_apply_start",
        call_sid=call_sid,
        transcript_len=len(speech_result or ""),
        confidence=confidence,
    )

    try:
        async with runtime.call_store.utterance_lock(call_sid):
            return await _apply_caller_utterance_locked(
                call_sid, speech_result, confidence, base_url
            )
    except UtteranceLockError:
        voice_warning("utterance_lock_contention", call_sid=call_sid)
        import main as m

        if call_sid and m.response_status.get(call_sid):
            bu = base_url.rstrip("/")
            poll = m.VoiceResponse()
            poll.redirect(f"{bu}/api/phone/respond?CallSid={call_sid}", method="POST")
            return UtteranceResult(
                mode="replace_call_twiml", replacement_twiml=str(poll)
            )
        from voice.twiml_stt import got_it_respond_twiml

        return UtteranceResult(
            mode="replace_call_twiml",
            replacement_twiml=got_it_respond_twiml(call_sid, base_url),
        )


async def _apply_caller_utterance_locked(
    call_sid: str,
    speech_result: str,
    confidence: float,
    base_url: str,
) -> UtteranceResult:
    """Process utterance while holding the per-call lock."""
    import main as m

    if not call_sid or not runtime.call_store.exists(call_sid):
        forwarding_phone = m.get_business_info().get("forwarding_phone")
        if forwarding_phone:
            voice_forward(
                "utterance_lost_session_forward",
                call_sid=call_sid,
                forward_kind="fallback",
                has_fallback_configured=True,
            )
            xml = str(m.forward_call_to_business(forwarding_phone, base_url, "English"))
            return UtteranceResult(mode="replace_call_twiml", replacement_twiml=xml)
        lost_twiml = m.VoiceResponse()
        lost_twiml.say("I'm sorry, I lost track of our conversation. Please call back.", voice="alice")
        return UtteranceResult(mode="replace_call_twiml", replacement_twiml=str(lost_twiml))

    call_data = m.active_calls[call_sid]

    if not (speech_result or "").strip():
        n = int(call_data.get("empty_speech_turns") or 0) + 1
        call_data["empty_speech_turns"] = n
        voice_info("utterance_empty_transcript", call_sid=call_sid, attempt=n)
        lang_code = m.get_twilio_language_code(call_data.get("detected_language") or "English")
        if n >= 4:
            goodbye_twiml = m.VoiceResponse()
            goodbye_twiml.say(
                "I'm still not hearing anything. Please try calling again from a quieter spot. Goodbye.",
                voice="alice",
            )
            goodbye_twiml.hangup()
            voice_warning(
                "utterance_empty_give_up",
                call_sid=call_sid,
                attempt=n,
            )
            m._persist_call_session(call_sid, call_data)
            return UtteranceResult(mode="replace_call_twiml", replacement_twiml=str(goodbye_twiml))
        use_deepgram = deepgram_stt_active(
            twilio_available=bool(m.TWILIO_AVAILABLE),
            twilio_client=m.twilio_client,
        )
        xml = empty_retry_twiml(
            base_url=base_url,
            language=lang_code,
            use_deepgram=use_deepgram,
            call_sid=call_sid,
            call_state=call_data,
        )
        m._persist_call_session(call_sid, call_data)
        return UtteranceResult(mode="replace_call_twiml", replacement_twiml=xml)

    # Per-call hard ceiling: a real (non-empty) utterance counts as a turn. If the call
    # has run too long or taken too many turns, wrap up gracefully and hang up rather than
    # letting cost accrue unbounded.
    call_data["turn_count"] = int(call_data.get("turn_count") or 0) + 1
    started_epoch = call_data.get("started_at_epoch")
    elapsed = (time.time() - started_epoch) if isinstance(started_epoch, (int, float)) else 0.0
    if call_data["turn_count"] > MAX_USER_TURNS or elapsed > MAX_CALL_SECONDS:
        voice_warning(
            "utterance_call_limit_reached",
            call_sid=call_sid,
            turn_count=call_data["turn_count"],
            elapsed_sec=int(elapsed),
        )
        wrap_twiml = m.VoiceResponse()
        forwarding_phone = m.get_business_info().get("forwarding_phone")
        if forwarding_phone:
            wrap_twiml.say(
                "Let me connect you with someone who can finish helping you. One moment.",
                voice="alice",
            )
            wrap_twiml.dial(forwarding_phone)
        else:
            wrap_twiml.say(
                "Thanks for calling. I've noted everything we discussed and someone will follow up. Goodbye.",
                voice="alice",
            )
            wrap_twiml.hangup()
        m._persist_call_session(call_sid, call_data)
        return UtteranceResult(mode="replace_call_twiml", replacement_twiml=str(wrap_twiml))

    # Plainly-Latin speech is always treated as English downstream (see the force-English
    # branch below), so skip the per-turn language-detection GPT call for it — that's the
    # common case, and it removes a full blocking round-trip of dead air before every reply.
    # Non-Latin transcripts still go through detection so the record/translate path can fire.
    if m._text_looks_latin(speech_result):
        current_detected_lang = "English"
    else:
        current_detected_lang = m.detect_language(speech_result)
    confidence_float = float(confidence) if confidence else 0.0
    previous_lang = call_data.get("detected_language")
    is_first_input = previous_lang is None

    if m.uses_non_latin_script(current_detected_lang) and (is_first_input or confidence_float < 0.5):
        if m._text_looks_latin(speech_result):
            current_detected_lang = "English"
            call_data["detected_language"] = "English"
        else:
            voice_info(
                "utterance_non_latin_record_path",
                call_sid=call_sid,
                lang=current_detected_lang,
                is_first_input=is_first_input,
                confidence=confidence_float,
            )
            call_data["detected_language"] = current_detected_lang
            record_twiml = m.VoiceResponse()
            prompt_text = (
                f"I detected you're speaking in {current_detected_lang}. "
                "For better accuracy, please speak again and press pound when done."
            )
            prompt_encoded = quote(prompt_text)
            tts_url = f"{base_url}/api/phone/tts-audio?text={prompt_encoded}&voice={m.get_tts_voice()}"
            record_twiml.play(tts_url)
            record_twiml.record(
                action=f"{base_url}/api/phone/process-recording",
                method="POST",
                max_length=15,
                finish_on_key="#",
                recording_status_callback=f"{base_url}/api/phone/recording-status",
            )
            m._persist_call_session(call_sid, call_data)
            return UtteranceResult(mode="replace_call_twiml", replacement_twiml=str(record_twiml))

    if m._text_looks_latin(speech_result):
        current_detected_lang = "English"
        call_data["detected_language"] = "English"

    if m.uses_non_latin_script(current_detected_lang):
        voice_debug(
            "utterance_non_latin_subsequent",
            call_sid=call_sid,
            lang=current_detected_lang,
        )

    if confidence_float < 0.3:
        voice_info("utterance_low_confidence", call_sid=call_sid, confidence=confidence_float)

    previous_lang = call_data.get("detected_language")
    if previous_lang != current_detected_lang:
        voice_info(
            "utterance_language",
            call_sid=call_sid,
            from_lang=previous_lang,
            to_lang=current_detected_lang,
        )
        call_data["detected_language"] = current_detected_lang
    detected_lang = current_detected_lang

    user_message = {"role": "user", "content": speech_result}
    call_data["conversation_history"].append(user_message)
    call_data["last_utterance_at"] = time.time()
    call_data["awaiting_caller_reply"] = False
    if m._suggests_booking(speech_result):
        call_data["booking_intent"] = True

    if m.should_forward_to_human(
        speech_result,
        "",
        call_sid=call_sid,
        client_id=str(call_data.get("client_id") or ""),
    ):
        _biz = m.get_business_info()
        forwarding_phone = (_biz.get("forwarding_phone") or "").strip()
        # DIAGNOSTIC: what tenant/config did the call actually load when deciding to forward?
        voice_info(
            "forward_lookup",
            call_sid=call_sid,
            session_client_id=str(call_data.get("client_id") or ""),
            loaded_biz_name=str(_biz.get("name") or "")[:40],
            has_forwarding_phone=bool(forwarding_phone),
            forwarding_phone_len=len(forwarding_phone),
        )
        if forwarding_phone:
            voice_forward(
                "caller_requested_human",
                call_sid=call_sid,
                client_id=str(call_data.get("client_id") or ""),
                forward_kind="fallback",
                has_fallback_configured=True,
            )
            call_data["outcome"] = "forwarded"
            m.call_log_set_outcome(call_sid, "forwarded")
            xml = str(m.forward_call_to_business(forwarding_phone, base_url, detected_lang))
            m._persist_call_session(call_sid, call_data)
            return UtteranceResult(mode="replace_call_twiml", replacement_twiml=xml)
        # Caller asked for a human but no transfer number is configured — flag it so the
        # generated reply is an honest "take a message" line, never a fake-human response.
        call_data["forward_unavailable"] = True

    m.response_status[call_sid] = {
        "status": "pending",
        "audio_url": None,
        "ai_text": None,
    }
    m._persist_call_session(call_sid, call_data)
    m.create_tracked_task(
        m.generate_response_async(call_sid, call_data, detected_lang, base_url),
        name=f"generate_response:{call_sid}",
    )
    voice_call_phase(
        "gpt_scheduled",
        call_sid=call_sid,
        client_id=str(call_data.get("client_id") or ""),
        lang=detected_lang,
    )
    return UtteranceResult(mode="tail_play_respond")
