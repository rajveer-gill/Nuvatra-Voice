"""
Billing-related configuration (single source of truth for overage pricing).
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger("nuvatra")

# USD per extra voice minute (monthly overage cron).
OVERAGE_PRICE_PER_MINUTE_DEFAULT = 0.15


def get_overage_price_per_minute() -> float:
    """Resolve overage price from env or default."""
    raw = (os.getenv("OVERAGE_PRICE_PER_MINUTE") or "").strip()
    if raw:
        try:
            price = float(raw)
            if price >= 0:
                return price
        except ValueError:
            _log.warning(
                "[BILLING] invalid_OVERAGE_PRICE_PER_MINUTE value=%r using default=%s",
                raw,
                OVERAGE_PRICE_PER_MINUTE_DEFAULT,
            )
    return OVERAGE_PRICE_PER_MINUTE_DEFAULT
