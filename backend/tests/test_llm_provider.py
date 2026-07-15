"""Provider shim: OpenAI/Anthropic routing by model prefix + message translation."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import llm_provider


def test_is_anthropic_model():
    assert llm_provider.is_anthropic_model("claude-haiku-4-5")
    assert llm_provider.is_anthropic_model("Claude-Sonnet-5")
    assert not llm_provider.is_anthropic_model("gpt-4o")
    assert not llm_provider.is_anthropic_model("gpt-4o-mini")
    assert not llm_provider.is_anthropic_model("")


def test_split_for_anthropic_folds_system_and_drops_leading_assistant():
    messages = [
        {"role": "system", "content": "main prompt"},
        {"role": "assistant", "content": "Hi, I'm maxie."},  # greeting — must be dropped
        {"role": "user", "content": "what are your hours?"},
        {"role": "assistant", "content": "9 to 5."},
        {"role": "system", "content": "booking nudge"},  # mid-array system — must fold in
        {"role": "user", "content": ""},  # empty — must be skipped
    ]
    system, conv = llm_provider._split_for_anthropic(messages)
    assert system == "main prompt\n\nbooking nudge"
    assert conv == [
        {"role": "user", "content": "what are your hours?"},
        {"role": "assistant", "content": "9 to 5."},
    ]


def test_split_for_anthropic_empty_falls_back_to_user():
    system, conv = llm_provider._split_for_anthropic(
        [{"role": "system", "content": "only system"}]
    )
    assert system == "only system"
    assert conv == [{"role": "user", "content": "(call started)"}]


def test_chat_routes_claude_to_anthropic(monkeypatch):
    fake_resp = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Our hours are 9 to 5. "),
            SimpleNamespace(type="text", text="How can I help?"),
        ]
    )
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp
    monkeypatch.setattr(llm_provider, "_anthropic_client", fake_client)
    # Guard: the Anthropic path must never touch the OpenAI client.
    monkeypatch.setattr(
        llm_provider.runtime, "client", MagicMock(side_effect=AssertionError)
    )

    out = llm_provider.chat(
        model="claude-haiku-4-5",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hours?"},
        ],
        temperature=0.8,
        max_tokens=200,
    )
    assert out == "Our hours are 9 to 5. How can I help?"
    kwargs = fake_client.messages.create.call_args[1]
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["system"] == "sys"
    assert kwargs["max_tokens"] == 200
    assert kwargs["temperature"] == 0.8
    assert kwargs["messages"] == [{"role": "user", "content": "hours?"}]


def test_chat_routes_gpt_to_openai(monkeypatch):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="gpt reply"))]
    )
    monkeypatch.setattr(llm_provider.runtime, "client", fake_client)

    out = llm_provider.chat(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0,
        max_tokens=120,
    )
    assert out == "gpt reply"
    kwargs = fake_client.chat.completions.create.call_args[1]
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["max_tokens"] == 120
    assert kwargs["temperature"] == 0
