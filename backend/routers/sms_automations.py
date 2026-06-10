"""SMS automations CRUD (plan-gated: Growth/Pro)."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

import database
import deps
from models import SmsAutomationCreate, SmsAutomationUpdate

try:
    from plans import get_plan_limits
except ImportError:  # pragma: no cover
    get_plan_limits = None  # type: ignore

logger = logging.getLogger("nuvatra")

router = APIRouter()


@router.get("/api/sms-automations")
def get_sms_automations(
    tenant: Optional[dict] = Depends(deps.require_active_subscription),
):
    """List SMS automations. Growth/Pro only."""
    cid = database._client_id()
    if not cid or cid == "default":
        if deps._settings_load_debug_enabled():
            logger.info(
                "settings_load_debug GET /api/sms-automations early_empty cid_default=%s",
                not cid or cid == "default",
            )
        return {"automations": []}
    if get_plan_limits:
        limits = get_plan_limits(tenant) if tenant else {}
        if limits.get("sms_automations_max", 0) <= 0:
            if deps._settings_load_debug_enabled():
                logger.info(
                    "settings_load_debug GET /api/sms-automations plan_has_no_automations_slot"
                )
            return {"automations": []}
    automations = database.db_sms_automations_get_all(cid)
    if deps._settings_load_debug_enabled():
        logger.info(
            "settings_load_debug GET /api/sms-automations client_id_prefix=%s count=%s",
            (str(cid)[:10] + "…") if cid else "none",
            len(automations) if isinstance(automations, list) else "na",
        )
    return {"automations": automations}


@router.post("/api/sms-automations")
def create_sms_automation(
    req: SmsAutomationCreate,
    tenant: Optional[dict] = Depends(deps.require_tenant),
    _: None = Depends(deps.require_active_subscription),
):
    """Create SMS automation. Growth: max 2, Pro: unlimited."""
    cid = database._client_id()
    if not cid or cid == "default":
        raise HTTPException(status_code=400, detail="No client context")
    if not tenant or not get_plan_limits:
        raise HTTPException(
            status_code=403, detail="Plan does not include SMS automations"
        )
    limits = get_plan_limits(tenant)
    if limits.get("sms_automations_max", 0) <= 0:
        raise HTTPException(
            status_code=403, detail="Plan does not include SMS automations"
        )
    count = database.db_sms_automations_count(cid)
    if count >= limits.get("sms_automations_max", 0):
        raise HTTPException(
            status_code=403,
            detail=f"Plan allows up to {limits.get('sms_automations_max')} automations",
        )
    automation_id = database.db_sms_automations_insert(
        cid, req.trigger, req.template or ""
    )
    if not automation_id:
        raise HTTPException(status_code=500, detail="Failed to create automation")
    return {"id": automation_id, "trigger": req.trigger, "template": req.template}


@router.patch("/api/sms-automations/{automation_id}")
def update_sms_automation(
    automation_id: int,
    req: SmsAutomationUpdate,
    _: None = Depends(deps.require_active_subscription),
):
    cid = database._client_id()
    if not cid or cid == "default":
        raise HTTPException(status_code=400, detail="No client context")
    ok = database.db_sms_automations_update(
        automation_id, cid, template=req.template, enabled=req.enabled
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"ok": True}


@router.delete("/api/sms-automations/{automation_id}")
def delete_sms_automation(
    automation_id: int, _: None = Depends(deps.require_active_subscription)
):
    cid = database._client_id()
    if not cid or cid == "default":
        raise HTTPException(status_code=400, detail="No client context")
    ok = database.db_sms_automations_delete(automation_id, cid)
    if not ok:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"ok": True}
