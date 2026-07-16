"""Regression tests for the Option C streaming Deepgram keep-alive / reconnect.

Bug: while the AI speaks (half-duplex gate), no caller audio is sent to Deepgram. A reply
longer than Deepgram's ~10s idle window let the listen socket close; the next caller frame hit
a dead socket and the handler silently `return`ed, dropping the call with no log. Fixed by
(1) sending KeepAlive during the gate and (2) logging + reconnecting instead of dropping.
"""
import asyncio
import json

import voice.media_ws_stream as mod


class FakeDG:
    def __init__(self) -> None:
        self.sent: list = []
        self.closed = False

    async def send(self, data) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _new_session() -> "mod._BidiSession":
    s = mod._BidiSession(websocket=object(), twilio_client=None)
    s.call_sid = "CAtest"
    return s


def test_keepalive_sends_when_idle():
    async def run():
        s = _new_session()
        s.dg_ws = FakeDG()
        s._last_dg_activity = -1000.0  # last send far in the past → past the keepalive window
        await s._keepalive_deepgram()
        return s.dg_ws.sent

    sent = asyncio.run(run())
    assert any(json.loads(m).get("type") == "KeepAlive" for m in sent)


def test_keepalive_is_throttled():
    async def run():
        s = _new_session()
        s.dg_ws = FakeDG()
        s._last_dg_activity = -1000.0
        await s._keepalive_deepgram()  # sends
        await s._keepalive_deepgram()  # activity just refreshed → throttled, no send
        return s.dg_ws.sent

    sent = asyncio.run(run())
    assert len(sent) == 1


def test_reconnect_swaps_socket_and_restarts_pump(monkeypatch):
    async def run():
        s = _new_session()
        old = FakeDG()
        s.dg_ws = old
        new = FakeDG()

        async def fake_connect():
            return new

        monkeypatch.setattr(mod, "connect_deepgram_listen", fake_connect)
        s._dg_task = asyncio.ensure_future(asyncio.sleep(3600))  # stand-in pump task to cancel
        ok = await s._reconnect_deepgram()
        await asyncio.sleep(0)  # let the new pump task drain the (empty) fake socket
        s._closing = True
        if s._dg_task is not None:
            s._dg_task.cancel()
        return ok, s.dg_ws is new, old.closed

    ok, swapped, old_closed = asyncio.run(run())
    assert ok is True
    assert swapped is True
    assert old_closed is True


def test_reconnect_failure_returns_false(monkeypatch):
    async def run():
        s = _new_session()
        s.dg_ws = FakeDG()

        async def boom():
            raise RuntimeError("deepgram unreachable")

        monkeypatch.setattr(mod, "connect_deepgram_listen", boom)
        s._dg_task = None
        return await s._reconnect_deepgram()

    assert asyncio.run(run()) is False
