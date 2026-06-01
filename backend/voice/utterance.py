"""Shared caller transcript → GPT/Twilio pipeline (Gather and Deepgram paths)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import quote

from observability import voice_call_phase, voice_debug, voice_forward, voice_info, voice_warning
from voice.stt_runtime import deepgram_stt_active
from voice.twiml_stt import empty_retry_twiml

_log = logging.getLogger("nuvatra")

_utterance_locks: dict[str, asyncio.Lock] = {}


def _lock_for(call_sid: str) -> asyncio.Lock:
    lk = _utterance_locks.get(call_sid)
    if lk is None:
        lk = asyncio.Lock()
        _utterance_locks[call_sid] = lk
    return lk


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

    async with _lock_for(call_sid):
        if not call_sid or call_sid not in m.active_calls:
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
            # Use a fresh variable name per branch so Python never treats TwiML locals as one shared `vr`
            # (assignments later in this function would otherwise make `vr` local for the whole body → UnboundLocalError).
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
            return UtteranceResult(mode="replace_call_twiml", replacement_twiml=xml)

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
        if m._suggests_booking(speech_result):
            call_data["booking_intent"] = True

        if m.should_forward_to_human(
            speech_result,
            "",
            call_sid=call_sid,
            client_id=str(call_data.get("client_id") or ""),
        ):
            forwarding_phone = m.get_business_info().get("forwarding_phone")
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
                return UtteranceResult(mode="replace_call_twiml", replacement_twiml=xml)

        m.response_status[call_sid] = {
            "status": "pending",
            "audio_url": None,
            "ai_text": None,
        }
        asyncio.create_task(m.generate_response_async(call_sid, call_data, detected_lang, base_url))
        voice_call_phase(
            "gpt_scheduled",
            call_sid=call_sid,
            client_id=str(call_data.get("client_id") or ""),
            lang=detected_lang,
        )
        return UtteranceResult(mode="tail_play_respond")
