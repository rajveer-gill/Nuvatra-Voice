"""Idempotent, resumable per-tenant provisioning for bulk onboarding.

`provision_one_tenant` runs the steps for a single store and records which ones
completed (`steps_done`). Re-running a task skips finished steps, so a partial
failure (e.g. Twilio hiccup on tenant #30) is recovered by re-running just the
unfinished tasks — never all-or-nothing. All collaborators are module-qualified
so they stay patchable and the import graph stays acyclic (no import of main).
"""

from __future__ import annotations

import asyncio
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
        # 1. Twilio number FIRST. db_tenant_create requires a valid number (and a
        #    tenant should never exist without one), so the number must be in hand
        #    before we create the row. Never double-buy: reuse a number already on
        #    the task (resume) or on an existing tenant row (partial prior run).
        if STEP_NUMBER not in steps:
            if not phone:
                existing = database.db_tenant_get_by_client_id(cid)
                existing_num = (
                    (existing.get("twilio_phone_number") or "").strip()
                    if existing
                    else ""
                )
                if existing_num:
                    phone = existing_num
                else:
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
            out["phone_e164"] = phone
            steps.add(STEP_NUMBER)

        # 2. Tenant row, now with a valid number. db_tenant_create is
        #    ON CONFLICT DO NOTHING; re-fetch to confirm and get the id.
        created_now = STEP_TENANT not in steps
        if created_now:
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
        # On first creation only, ensure the number is assigned (covers a tenant
        # that pre-existed without one). Skipped on resume to avoid a redundant write.
        if created_now and phone and (tenant.get("twilio_phone_number") or "").strip() != phone:
            database.db_tenant_set_twilio_phone(tenant_id, phone)

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


def _provision_and_release(task: dict, **kw) -> dict:
    """Run one tenant in a worker thread, then return that thread's pooled DB
    connection (the request middleware won't — this isn't a request)."""
    try:
        return provision_one_tenant(task, **kw)
    finally:
        database.db_release_thread_connection()


async def run_provisioning_job(
    job_id: str,
    *,
    base_url: str,
    account_sid: str,
    auth_token: str,
    default_area_code: Optional[str] = None,
    concurrency: int = 6,
) -> dict:
    """Process a job's unfinished tasks with bounded concurrency. Each tenant's
    blocking work runs in a thread; results persist as they complete. Returns a
    summary {done, failed, total}. Safe to re-invoke (resume) — finished tasks
    are skipped at the SQL level and the step machine is idempotent."""
    database.db_provisioning_job_set_status(job_id, "running")
    tasks = database.db_provisioning_tasks_for_job(job_id, only_unfinished=True)
    sem = asyncio.Semaphore(max(1, concurrency))
    done = 0
    failed = 0

    async def _one(task: dict):
        nonlocal done, failed
        async with sem:
            result = await asyncio.to_thread(
                _provision_and_release,
                task,
                base_url=base_url,
                account_sid=account_sid,
                auth_token=auth_token,
                default_area_code=default_area_code,
            )
            await asyncio.to_thread(
                database.db_provisioning_task_save,
                task["id"],
                status=result["status"],
                steps_done=result["steps_done"],
                phone_e164=result.get("phone_e164"),
                error=result.get("error"),
            )
            if result["status"] == "done":
                done += 1
            else:
                failed += 1

    try:
        await asyncio.gather(*[_one(t) for t in tasks], return_exceptions=False)
    finally:
        await asyncio.to_thread(database.db_release_thread_connection)
    database.db_provisioning_job_set_status(job_id, "failed" if failed else "done")
    return {"done": done, "failed": failed, "total": len(tasks)}
