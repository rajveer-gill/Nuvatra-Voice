"""Leads API (plan-gated: Growth/Pro only)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

import database
import deps
import runtime

try:
    from plans import get_plan_limits
except ImportError:  # pragma: no cover - plans module always present in practice
    get_plan_limits = None  # type: ignore

router = APIRouter()


@router.get("/api/leads")
def get_leads(
    tenant: Optional[dict] = Depends(deps.require_tenant),
    _: None = Depends(deps.require_active_subscription),
):
    """Get leads for the current tenant. Growth/Pro only; Starter returns empty."""
    cid = database._client_id()
    if not cid or cid == "default":
        return {"leads": []}
    if tenant and get_plan_limits:
        limits = get_plan_limits(tenant)
        if not limits.get("has_lead_capture"):
            return {"leads": []}
    leads = database.db_leads_get_all(cid, 100) if runtime.USE_DB else []
    return {"leads": leads}
