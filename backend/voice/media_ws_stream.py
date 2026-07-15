"""Option C: bidirectional Twilio Media Stream — one persistent stream for the whole call.

Unlike the batch path (per-turn <Connect><Stream> for STT only, AI reply via <Play> of a
fully-synthesized mp3), this keeps a single stream open and sends the AI reply back as
outbound mulaw/8000 frames over the same socket, so first audio starts in ~hundreds of ms
and the caller can barge in (we send `clear` to flush Twilio's buffer and stop the stream).

Crucially it REUSES the existing brain untouched:
  - apply_caller_utterance(): records the turn, handles forward/limits/language, schedules
    generate_response_async, and sets runtime.call_store.response_status.
  - generate_response_async(): produces `ai_text` with ALL booking/directive/SMS side
    effects (the moat). We just stream that text instead of turning it into a <Play> URL.

Gated by config_service.voice_streaming_enabled() (VOICE_STREAMING_TTS); off = untouched.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from typing import Any, Optional

import websockets
from fastapi import WebSocket

import config_service
import runtime
from observability import voice_info, voice_transcript, voice_warning
from voice.deepgram_bridge import (
    DEEPGRAM_MODEL,
    connect_deepgram_listen,
    parse_deepgram_transcript_message,
)
from voice.media_token import token_stream_generation, verify_pending_media_stream_token
from voice.stt_config import utterance_finalize_debounce_ms
from voice.streaming_tts import stream_tts_ulaw_frames
from voice.twilio_call import safe_twilio_call_update
from voice.twilio_media import parse_twilio_media_message, twilio_media_payload_bytes, twilio_start_meta
from voice.utterance import apply_caller_utterance

_log = logging.getLogger("nuvatra")

_FRAME_SEC = 0.02  # 20 ms per mulaw frame — paced real-time so barge-in stops within a frame.
_REPLY_WAIT_SEC = 25.0  # max wait for the brain to produce ai_text before giving up the turn.
_HANDSHAKE_SEC = 25.0


class _BidiSession:
    def __init__(self, websocket: WebSocket, twilio_client: Any) -> None:
        self.ws = websocket
        self.twilio_client = twilio_client
        self.call_sid: Optional[str] = None
        self.stream_sid: Optional[str] = None
        self.base_url = ""
        self.voice = "fable"
        self.speed = 1.0
        self._call_data: dict = {}
        self.dg_ws: Any = None
        self.speaking = False
        self.interrupt = asyncio.Event()
        self._barge_cleared = False
        self._closing = False
        self.utterance_q: "asyncio.Queue[tuple[str, float]]" = asyncio.Queue()
        self.debounce_sec = utterance_finalize_debounce_ms() / 1000.0
        # utterance accumulation
        self._finals: list[str] = []
        self._interim = ""
        self._conf = 0.0
        self._commit_task: Optional[asyncio.Task[None]] = None

    # ---- outbound websocket messages (Twilio bidirectional protocol) ----
    async def _send(self, obj: dict) -> None:
        await self.ws.send_text(json.dumps(obj))

    async def _send_media(self, frame: bytes) -> None:
        await self._send({
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {"payload": base64.b64encode(frame).decode("ascii")},
        })

    async def _send_clear(self) -> None:
        await self._send({"event": "clear", "streamSid": self.stream_sid})

    async def _send_mark(self, name: str) -> None:
        await self._send({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})

    async def _close(self) -> None:
        try:
            await self.ws.close()
        except Exception:
            pass

    # ---- speaking (stream TTS frames out, interruptible) ----
    async def _speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self._closing:
            return
        self.speaking = True
        self.interrupt.clear()
        self._barge_cleared = False
        loop = asyncio.get_running_loop()
        frame_q: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()

        def producer() -> None:
            try:
                for fr in stream_tts_ulaw_frames(text, self.voice, model="tts-1", speed=self.speed):
                    if self.interrupt.is_set():
                        break
                    loop.call_soon_threadsafe(frame_q.put_nowait, fr)
            except Exception:
                _log.exception("bidi_tts_producer_failed call_sid=%s", self.call_sid)
            finally:
                loop.call_soon_threadsafe(frame_q.put_nowait, None)

        threading.Thread(target=producer, daemon=True).start()
        sent = 0
        while True:
            fr = await frame_q.get()
            if fr is None or self.interrupt.is_set():
                break
            await self._send_media(fr)
            sent += 1
            await asyncio.sleep(_FRAME_SEC)
        interrupted = self.interrupt.is_set()
        if interrupted and not self._barge_cleared:
            await self._send_clear()
        elif not interrupted:
            await self._send_mark("reply_end")
        self.speaking = False
        voice_info("bidi_reply_spoken", call_sid=self.call_sid, frames=sent, interrupted=interrupted)

    async def _barge_in(self) -> None:
        """Caller spoke while we were talking: flush Twilio's buffer and stop the stream."""
        if self.speaking and not self._barge_cleared:
            self._barge_cleared = True
            self.interrupt.set()
            await self._send_clear()
            voice_info("bidi_barge_in", call_sid=self.call_sid)

    # ---- utterance accumulation + debounced commit ----
    def _on_transcript(self, text: str, is_final: bool, conf: float) -> None:
        t = (text or "").strip()
        if not t:
            if is_final and (self._finals or self._interim):
                self._schedule_commit()
            return
        # Any speech while we're talking is a barge-in.
        if self.speaking:
            asyncio.create_task(self._barge_in())
        if is_final:
            self._finals.append(t)
            self._conf = max(self._conf, conf)
            self._schedule_commit()
        else:
            self._interim = t
            self._conf = max(self._conf, conf)

    def _schedule_commit(self) -> None:
        if self._commit_task and not self._commit_task.done():
            self._commit_task.cancel()
        self._commit_task = asyncio.create_task(self._debounced_commit())

    async def _debounced_commit(self) -> None:
        try:
            await asyncio.sleep(self.debounce_sec)
        except asyncio.CancelledError:
            return
        text = " ".join(self._finals).strip() or self._interim.strip()
        conf = self._conf
        self._finals, self._interim, self._conf = [], "", 0.0
        if text:
            await self.utterance_q.put((text, conf))

    # ---- turn: reuse the existing brain, then stream the reply ----
    async def _await_reply(self) -> Optional[str]:
        deadline = time.monotonic() + _REPLY_WAIT_SEC
        while time.monotonic() < deadline:
            st = runtime.call_store.response_status.get(self.call_sid or "", {})
            status = st.get("status")
            if status == "ready":
                return (st.get("ai_text") or "").strip()
            if status == "forward":
                return None
            await asyncio.sleep(0.05)
        return ""

    async def _run_turn(self, text: str, conf: float) -> None:
        voice_transcript("caller_said", call_sid=self.call_sid, text=text)
        result = await apply_caller_utterance(self.call_sid or "", text, conf, self.base_url)
        # Forward / limits / lost-session / language-record all come back as a full TwiML doc:
        # REST-replace the call with it (that supersedes the <Connect> stream and ends the WS).
        if result.mode == "replace_call_twiml" and result.replacement_twiml:
            await safe_twilio_call_update(
                self.twilio_client, self.call_sid, result.replacement_twiml, op="bidi_replace_twiml"
            )
            self._closing = True
            await self._close()
            return
        ai_text = await self._await_reply()
        st = runtime.call_store.response_status.get(self.call_sid or "", {})
        if st.get("status") == "forward":
            fp = st.get("forwarding_phone")
            runtime.call_store.response_status.pop(self.call_sid or "", None)
            if fp:
                import main as m
                xml = str(m.forward_call_to_business(fp, self.base_url, "English"))
                await safe_twilio_call_update(self.twilio_client, self.call_sid, xml, op="bidi_forward")
            self._closing = True
            await self._close()
            return
        runtime.call_store.response_status.pop(self.call_sid or "", None)
        if ai_text:
            await self._speak(ai_text)

    async def _drive_turns(self) -> None:
        while not self._closing:
            text, conf = await self.utterance_q.get()
            if self._closing:
                return
            try:
                await self._run_turn(text, conf)
            except Exception:
                _log.exception("bidi_run_turn_failed call_sid=%s", self.call_sid)

    async def _pump_deepgram(self) -> None:
        try:
            async for message in self.dg_ws:
                if not isinstance(message, str):
                    continue
                parsed = parse_deepgram_transcript_message(message)
                if not parsed:
                    continue
                t, is_final, conf = parsed
                self._on_transcript(t, is_final, conf)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception:
            _log.exception("bidi_pump_deepgram_failed call_sid=%s", self.call_sid)

    # ---- handshake, greeting, main loop ----
    async def run(self) -> None:
        await self.ws.accept()
        voice_info("bidi_ws_open", path="/api/phone/media-stream")
        if not await self._handshake():
            await self._close()
            return
        # Tenant context for get_business_info() in this asyncio task.
        import database
        cid = str((self._call_data or {}).get("client_id") or "").strip()
        if cid:
            database.set_request_client_id(cid)
        try:
            self.dg_ws = await connect_deepgram_listen()
            voice_info("deepgram_connect_ok", call_sid=self.call_sid, model=DEEPGRAM_MODEL)
        except Exception as e:
            voice_warning("bidi_deepgram_connect_failed", call_sid=self.call_sid, detail=str(e)[:200])
            await self._close()
            return

        dg_task = asyncio.create_task(self._pump_deepgram())
        turn_task = asyncio.create_task(self._drive_turns())
        # Greeting first (interruptible like any reply).
        try:
            import voice_service
            payload = voice_service.build_phone_greeting_payload(config_service.get_business_info())
            self.voice = payload.get("voice") or self.voice
            asyncio.create_task(self._speak(payload.get("spoken_text") or ""))
        except Exception:
            _log.exception("bidi_greeting_failed call_sid=%s", self.call_sid)

        try:
            await self._inbound_loop()
        finally:
            self._closing = True
            for tk in (dg_task, turn_task):
                tk.cancel()
            try:
                await self.dg_ws.close()
            except Exception:
                pass
            await self._close()

    async def _handshake(self) -> bool:
        deadline = time.monotonic() + _HANDSHAKE_SEC
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.receive(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            if raw.get("type") == "websocket.disconnect":
                return False
            text = raw.get("text")
            if not isinstance(text, str):
                continue
            ev = parse_twilio_media_message(text)
            if not ev:
                continue
            if ev.get("event") == "start":
                return self._accept_start(ev)
            # ignore 'connected' and any pre-start media
        return False

    def _accept_start(self, ev: dict) -> bool:
        import main as m
        call_sid, stream_sid, cp = twilio_start_meta(ev)
        token = (cp or {}).get("token") or ""
        self.call_sid = call_sid
        self.stream_sid = stream_sid
        row = m.active_calls.get(call_sid or "") or {}
        max_gen = runtime.call_store.get_media_stream_max_gen(call_sid or "")
        if max_gen < 1:
            max_gen = int(row.get("media_stream_gen") or 0)
        voice_info(
            "bidi_ws_handshake",
            call_sid=call_sid or "",
            stream_sid_present=bool(stream_sid),
            has_token=bool(token),
            max_gen=max_gen,
            token_gen=token_stream_generation(token),
        )
        if not call_sid or not stream_sid or not token or max_gen < 1:
            return False
        if not verify_pending_media_stream_token(token, call_sid, max_issued_generation=max_gen):
            voice_warning("bidi_ws_invalid_token", call_sid=call_sid)
            return False
        base = (row.get("twilio_public_base_url") or "").strip()
        if not base:
            try:
                base = (m._public_base_url() or "").strip()
            except Exception:
                base = ""
        if not base:
            voice_warning("bidi_ws_missing_base_url", call_sid=call_sid)
            return False
        self.base_url = base
        self._call_data = row
        self.speed = config_service.get_tts_speed()
        voice_info("bidi_stream_start", call_sid=call_sid)
        return True

    async def _inbound_loop(self) -> None:
        while not self._closing:
            try:
                raw = await asyncio.wait_for(self.ws.receive(), timeout=30.0)
            except asyncio.TimeoutError:
                continue
            if raw.get("type") == "websocket.disconnect":
                voice_info("bidi_ws_close", reason="client_disconnect", call_sid=self.call_sid)
                return
            text = raw.get("text")
            if not isinstance(text, str):
                continue
            ev = parse_twilio_media_message(text)
            if not ev:
                continue
            kind = ev.get("event")
            if kind == "media":
                payload = twilio_media_payload_bytes(ev)
                if payload and self.dg_ws:
                    try:
                        await self.dg_ws.send(payload)
                    except Exception:
                        return
            elif kind == "stop":
                voice_info("bidi_ws_close", reason="twilio_stop", call_sid=self.call_sid)
                return


async def handle_bidirectional_media(websocket: WebSocket, twilio_client: Any) -> None:
    session = _BidiSession(websocket, twilio_client)
    try:
        await session.run()
    except Exception:
        _log.exception("bidi_media_unhandled")
        try:
            await websocket.close()
        except Exception:
            pass
