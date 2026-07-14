"""Provider-agnostic voice-brain chat shim.

The receptionist brain is selected by VOICE_LLM_MODEL. This routes that call to
OpenAI (default) or Anthropic purely by model-id prefix, so the brain can be
A/B'd via env — set VOICE_LLM_MODEL=claude-haiku-4-5 to run on Claude — without
touching the call sites in conversation_service. The OpenAI path is unchanged
(it delegates verbatim to runtime.client), so existing tests that mock
runtime.client.chat.completions.create keep working on the default model.

Anthropic client is lazy + bounded-timeout, mirroring runtime.py's OpenAI proxy:
the SDK default is 600s, which on a live phone call stalls the caller — bound it
so a hung request fails fast into the graceful TTS fallback instead.
"""

from __future__ import annotations

import os
from typing import Optional

import runtime

_anthropic_client = None


def _new_anthropic_client():
    import anthropic

    return anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=float(
            os.getenv("ANTHROPIC_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", "12"))
        ),
        max_retries=int(
            os.getenv("ANTHROPIC_MAX_RETRIES", os.getenv("OPENAI_MAX_RETRIES", "1"))
        ),
    )


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        print("[INIT] Creating Anthropic client (lazy)...")
        _anthropic_client = _new_anthropic_client()
        print("[OK] Anthropic client created successfully")
    return _anthropic_client


def is_anthropic_model(model: str) -> bool:
    return (model or "").strip().lower().startswith("claude")


def _split_for_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Translate OpenAI-style messages to Anthropic's shape.

    - All role=="system" messages (including any injected mid-array, e.g. the
      booking nudge) fold into the single top-level `system` string — Haiku 4.5
      does not support mid-conversation system messages.
    - The remaining user/assistant turns become `messages`, dropping any leading
      assistant (the call's first history turn is the AI greeting; Anthropic
      requires the first message to be `user`) and skipping empty content.
    """
    system = "\n\n".join(
        (m.get("content") or "").strip()
        for m in messages
        if m.get("role") == "system" and (m.get("content") or "").strip()
    )
    conv = [
        {"role": m["role"], "content": (m.get("content") or "").strip()}
        for m in messages
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    while conv and conv[0]["role"] == "assistant":
        conv.pop(0)
    if not conv:
        conv = [{"role": "user", "content": "(call started)"}]
    return system, conv


def chat(
    model: str,
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: Optional[float] = None,
) -> str:
    """Run one non-streaming chat completion and return the reply text.

    Routes to Anthropic when `model` is a Claude model, else OpenAI. No thinking/
    effort on the Anthropic path — Haiku 4.5 wants none for lowest voice latency
    (and `effort` errors on Haiku 4.5)."""
    if is_anthropic_model(model):
        system, conv = _split_for_anthropic(messages)
        kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": conv}
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = _anthropic().messages.create(**kwargs)
        return "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )

    # OpenAI path — unchanged behavior (delegates to the shared runtime client).
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = runtime.client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""
