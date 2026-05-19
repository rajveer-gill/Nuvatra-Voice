"""Tests for centralized overage pricing."""
import os

from billing_config import OVERAGE_PRICE_PER_MINUTE_DEFAULT, get_overage_price_per_minute


def test_default_overage_price_is_fifteen_cents():
    assert OVERAGE_PRICE_PER_MINUTE_DEFAULT == 0.15


def test_get_overage_price_uses_env_when_valid(monkeypatch):
    monkeypatch.setenv("OVERAGE_PRICE_PER_MINUTE", "0.20")
    assert get_overage_price_per_minute() == 0.20


def test_get_overage_price_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("OVERAGE_PRICE_PER_MINUTE", raising=False)
    assert get_overage_price_per_minute() == 0.15
