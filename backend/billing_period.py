"""
Billing period boundaries keyed off tenant anchor (not calendar month).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple


def _parse_anchor(anchor_raw: object) -> datetime:
    if isinstance(anchor_raw, datetime):
        dt = anchor_raw
    elif isinstance(anchor_raw, str) and anchor_raw.strip():
        dt = datetime.fromisoformat(anchor_raw.replace("Z", "+00:00"))
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _anchor_day_for_month(year: int, month: int, anchor_day: int) -> int:
    return min(anchor_day, monthrange(year, month)[1])


def billing_period_for_tenant(
    tenant: dict,
    now: Optional[datetime] = None,
) -> Tuple[datetime, datetime, str]:
    """
    Return (period_start inclusive, period_end exclusive, period_key) in UTC.

    period_key is the ISO date of period_start (stable id for DB counters).
    Anchor: billing_period_anchor_at, else created_at, else now.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    anchor = _parse_anchor(
        tenant.get("billing_period_anchor_at") or tenant.get("created_at")
    )
    anchor_day = anchor.day
    y, m = now.year, now.month
    start_day = _anchor_day_for_month(y, m, anchor_day)
    period_start = datetime(y, m, start_day, tzinfo=timezone.utc)
    if now < period_start:
        if m == 1:
            py, pm = y - 1, 12
        else:
            py, pm = y, m - 1
        start_day = _anchor_day_for_month(py, pm, anchor_day)
        period_start = datetime(py, pm, start_day, tzinfo=timezone.utc)
    if m == 12:
        ny, nm = y + 1, 1
    else:
        ny, nm = y, m + 1
    end_day = _anchor_day_for_month(ny, nm, anchor_day)
    period_end = datetime(ny, nm, end_day, tzinfo=timezone.utc)
    if period_end <= period_start:
        period_end = period_start + timedelta(days=28)
    period_key = period_start.date().isoformat()
    return period_start, period_end, period_key
