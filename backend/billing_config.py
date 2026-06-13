"""
Billing-related configuration (single source of truth for overage pricing).
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger("nuvatra")

# USD per extra voice minute (monthly overage cron).
OVERAGE_PRICE_PER_MINUTE_DEFAULT = 0.15
# USD per extra SMS over the plan cap (monthly overage cron).
OVERAGE_PRICE_PER_SMS_DEFAULT = 0.03


def _resolve_price(env_var: str, default: float) -> float:
    raw = (os.getenv(env_var) or "").strip()
    if raw:
        try:
            price = float(raw)
            if price >= 0:
                return price
        except ValueError:
            _log.warning("[BILLING] invalid_%s value=%r using default=%s", env_var, raw, default)
    return default


def get_overage_price_per_minute() -> float:
    """Resolve voice overage price from env or default."""
    return _resolve_price("OVERAGE_PRICE_PER_MINUTE", OVERAGE_PRICE_PER_MINUTE_DEFAULT)


def get_overage_price_per_sms() -> float:
    """Resolve SMS overage price from env or default."""
    return _resolve_price("OVERAGE_PRICE_PER_SMS", OVERAGE_PRICE_PER_SMS_DEFAULT)
