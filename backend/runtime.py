"""Mutable process-wide runtime state, owned in one place.

Several values are decided at startup and then read from many call sites — most
importantly ``USE_DB`` (flipped on once the database connects). When the codebase
lived in a single ``main.py`` module these could be plain module globals. As the
app is split into routers, those routers must read the *live* value, so the state
lives here and is always accessed by attribute on the module:

    import runtime
    if runtime.USE_DB:
        ...

NEVER ``from runtime import USE_DB`` — that binds a one-time snapshot of the bool
and would silently miss the startup flip. Tests patch ``runtime.USE_DB``.
"""

from __future__ import annotations

import os
from typing import List

import openai

# In-memory appointment/message stores — the fallback used ONLY when USE_DB is
# False (local/dev with no Postgres). main.py aliases its module globals to these
# exact list objects, so the (future) analytics/appointments routers can share
# the same data via runtime.appointments / runtime.messages. Only ever mutated
# (.append/.extend), never reassigned — so the alias stays valid.
appointments: List[dict] = []
messages: List[dict] = []

# True once init_db() has successfully connected. Written by the startup paths in
# main.py (init_db_background) and deps._ensure_db_ready; read across the app.
USE_DB: bool = False

# True once the `database` module imported cleanly (set in main.py). Guards the
# deferred-init path in deps._ensure_db_ready.
_db_imported: bool = False

# Twilio REST client singleton, created once at startup in main.py (or None when
# Twilio is unavailable / unconfigured). Shared by main's phone code and
# sms_service.send_sms — read as runtime.twilio_client so both see the same object.
twilio_client = None

# Lazy OpenAI client — created on first use so import doesn't block port binding.
# `client` is a stable proxy instance (created once, never reassigned), so other
# modules may `from runtime import client` safely OR use runtime.client; the real
# SDK object lives behind it in `_openai_client` and is created on first access.
# Both the proxy and _ensure_openai_client() mutate the same runtime._openai_client.
_openai_client = None


def _new_openai_client():
    """Construct the OpenAI client with a bounded timeout and retry budget.

    The SDK defaults to a 600s timeout. On a live phone call that means a
    single hung request stalls the caller indefinitely (and, when issued on
    the event loop, every concurrent call with it). Bound both so a slow
    request fails fast into the graceful TTS fallback instead of hanging.
    Worst-case latency is timeout * (max_retries + 1); keep both small.
    Tune via OPENAI_TIMEOUT_SECONDS / OPENAI_MAX_RETRIES.
    """
    return openai.OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "12")),
        max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "1")),
    )


class _LazyOpenAIClient:
    """Proxy that creates the real OpenAI client on first attribute access."""

    def __getattr__(self, name):
        global _openai_client
        if _openai_client is None:
            print("[INIT] Creating OpenAI client (lazy)...")
            _openai_client = _new_openai_client()
            print("[OK] OpenAI client created successfully")
        return getattr(_openai_client, name)


client = _LazyOpenAIClient()


def _ensure_openai_client():
    """Eagerly create the client if not yet initialized."""
    global _openai_client
    if _openai_client is None:
        print("[INIT] Creating OpenAI client...")
        _openai_client = _new_openai_client()
        print("[OK] OpenAI client created successfully")


# Per-call session store (Redis when REDIS_URL set, else in-memory) — a stable
# singleton created once at import. Shared by main's phone routes and voice_service's
# call-session helpers; always read as runtime.call_store so both see the same store.
from voice.call_session_store import get_call_session_store as _get_call_session_store

call_store = _get_call_session_store()

