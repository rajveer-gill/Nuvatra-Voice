"""Idempotent, resumable per-tenant provisioning for bulk onboarding.

`provision_one_tenant` runs the steps for a single store and records which ones
completed (`steps_done`). Re-running a task skips finished steps, so a partial
failure (e.g. Twilio hiccup on tenant #30) is recovered by re-running just the
unfinished tasks — never all-or-nothing. All collaborators are module-qualified
so they stay patchable and the import graph stays acyclic (no import of main).
"""

from __future__ import annotations

import logging
from typing import Optional

import clerk_service
import config_service
import database
import twilio_provision

logger = logging.getLogger("nuvatra")

STEP_TENANT = "tenant_created"
STEP_NUMBER = "number_purchased"
STEP_CONFIG = "config_seeded"
STEP_CLERK = "clerk_invited"


def provision_one_tenant(
    task: dict,
    *,
    base_url: str,
    account_sid: str,
    auth_token: str,
    default_area_code: Optional[str] = None,
) -> dict:
    """Provision one tenant idempotently. Returns the updated task dict with
    `steps_done`, `phone_e164`, and `status` ('done' | 'failed') / `error`."""
    steps = set(task.get("steps_done") or [])
    cid = task["client_id"]
    out = dict(task)
    out["error"] = None
    phone = (task.get("phone_e164") or "").strip() or None

    try:
        # 1. Tenant row — idempotent (db_tenant_create is ON CONFLICT DO NOTHING).
        if STEP_TENANT not in steps:
            database.db_tenant_create(
                client_id=cid,
                name=task.get("name") or "",
                twilio_phone_number=phone or "",
                plan=task.get("plan") or "free",
            )
            steps.add(STEP_TENANT)

        tenant = database.db_tenant_get_by_client_id(cid)
        if not tenant:
            raise RuntimeError("tenant_row_missing_after_create")
        tenant_id = str(tenant.get("id") or "")
        phone = phone or ((tenant.get("twilio_phone_number") or "").strip() or None)

        # 2. Twilio number — never re-buy: skip if the tenant already has one.
        if STEP_NUMBER not in steps:
            if not phone:
                res = twilio_provision.purchase_number(
                    account_sid=account_sid,
                    auth_token=auth_token,
                    base_url=base_url,
                    area_code=task.get("area_code") or default_area_code,
                )
                if not res.get("ok"):
                    raise RuntimeError(
                        "twilio_purchase_failed:" + ",".join(res.get("errors") or [])
                    )
                phone = res["phone_e164"]
                if not database.db_tenant_set_twilio_phone(tenant_id, phone):
                    raise RuntimeError("twilio_phone_assign_failed")
            out["phone_e164"] = phone
            steps.add(STEP_NUMBER)

        # 3. Seed business config — idempotent upsert.
        if STEP_CONFIG not in steps:
            cfg = config_service._default_client_config_data(
                cid, task.get("plan") or "free"
            )
            if phone:
                cfg["phone"] = phone
            if task.get("name"):
                cfg["business_name"] = task["name"]
            config_service.save_raw_client_config(cid, cfg)
            steps.add(STEP_CONFIG)

        # 4. Clerk owner invite/link — idempotent upsert inside. A placeholder or
        #    already-registered email returns a non-fatal clerk_error; we still
        #    consider the step done (the invite row is stored / user is linked).
        if STEP_CLERK not in steps and (task.get("email") or "").strip():
            clerk_service._clerk_link_email_to_tenant(task["email"], tenant_id)
            steps.add(STEP_CLERK)

        out["steps_done"] = sorted(steps)
        out["status"] = "done"
    except Exception as e:
        out["steps_done"] = sorted(steps)
        out["status"] = "failed"
        out["error"] = str(e)[:500]
        logger.warning(
            "provision_one_tenant failed cid=%s step_after=%s err=%s",
            cid,
            sorted(steps),
            type(e).__name__,
        )
    return out
