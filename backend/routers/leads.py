"""Leads API (plan-gated: Growth/Pro only)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import booking_service
import database
import deps
import runtime
import sms_service

try:
    from plans import get_plan_limits
except ImportError:  # pragma: no cover - plans module always present in practice
    get_plan_limits = None  # type: ignore

router = APIRouter()


class LeadTextBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


@router.get("/api/leads")
def get_leads(
    tenant: Optional[dict] = Depends(deps.require_tenant),
    _: None = Depends(deps.require_active_subscription),
):
    """Get leads for the current tenant. Growth/Pro only; Starter returns empty."""
    # Bind tenant context in the handler: the client_id contextvar set inside the sync
    # require_tenant dependency does not survive into this sync endpoint, so
    # database._client_id() would resolve to "default" and always return no leads.
    cid = deps._bind_tenant_db_context(tenant)
    if not cid or cid == "default":
        return {"leads": []}
    if tenant and get_plan_limits:
        limits = get_plan_limits(tenant)
        if not limits.get("has_lead_capture"):
            return {"leads": []}
    leads = database.db_leads_get_all(cid, 100) if runtime.USE_DB else []
    return {"leads": leads}


@router.post("/api/leads/{lead_id}/text")
def text_lead(
    lead_id: int,
    body: LeadTextBody,
    request: Request,
    tenant: Optional[dict] = Depends(deps.require_tenant),
    _: None = Depends(deps.require_active_subscription),
):
    """Send a follow-up text to a captured lead from the business number. Growth/Pro only."""
    cid = deps._bind_tenant_db_context(tenant)
    if tenant and get_plan_limits and not get_plan_limits(tenant).get("has_lead_capture"):
        raise HTTPException(status_code=403, detail="Lead follow-up is available on Growth and Pro plans")
    lead = database.db_leads_get_by_id(lead_id, cid) if runtime.USE_DB else None
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    to_phone = (lead.get("phone") or "").strip()
    if not to_phone:
        raise HTTPException(status_code=400, detail="This lead has no phone number to text")
    sent = sms_service.send_sms(
        to_phone, body.text.strip(), from_override=booking_service._tenant_sms_from_number()
    )
    deps.audit_log(
        "user",
        "lead_texted",
        resource_type="lead",
        resource_id=str(lead_id),
        details={"text_sms_sent": bool(sent)},
        request=request,
    )
    return {"success": True, "text_sms_sent": sent}
