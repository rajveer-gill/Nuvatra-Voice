"""Admin background bulk-onboarding endpoints.

Submit a batch of tenants -> returns a job id immediately and provisions them in
the background (Twilio auto-purchase + config + Clerk invite), one idempotent,
resumable task per tenant. Replaces the synchronous bulk-create that timed out
and left half-provisioned tenants on partial failure.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

import database
import deps
import provisioning
from models import ProvisioningJobRequest

router = APIRouter()

# Hold references to in-flight worker tasks so they aren't garbage-collected.
_bg_tasks: set = set()


def _provisioning_creds() -> tuple[str, str, str]:
    return (
        (os.getenv("PUBLIC_BASE_URL") or "").strip(),
        (os.getenv("TWILIO_ACCOUNT_SID") or "").strip(),
        (os.getenv("TWILIO_AUTH_TOKEN") or "").strip(),
    )


def _kick_worker(job_id: str, default_area_code: Optional[str]) -> None:
    base_url, sid, tok = _provisioning_creds()
    task = asyncio.create_task(
        provisioning.run_provisioning_job(
            job_id,
            base_url=base_url,
            account_sid=sid,
            auth_token=tok,
            default_area_code=default_area_code,
        )
    )
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


@router.post("/api/admin/provisioning/jobs")
async def create_provisioning_job(
    req: ProvisioningJobRequest,
    admin: str = Depends(deps.require_admin),
):
    """Validate the batch, persist a job + per-tenant tasks, start the worker."""
    seen: set = set()
    for r in req.tenants:
        cid = (r.client_id or "").strip()
        if not cid:
            raise HTTPException(status_code=400, detail="client_id required for every tenant")
        if cid in seen:
            raise HTTPException(status_code=400, detail=f"duplicate client_id in batch: {cid}")
        seen.add(cid)

    base_url, sid, tok = _provisioning_creds()
    if not base_url or not sid or not tok:
        raise HTTPException(
            status_code=503,
            detail="Provisioning not configured (PUBLIC_BASE_URL + TWILIO_ACCOUNT_SID/AUTH_TOKEN required)",
        )

    job_id = uuid.uuid4().hex
    if not database.db_provisioning_job_create(job_id, admin, len(req.tenants)):
        raise HTTPException(status_code=500, detail="Failed to create provisioning job")
    for r in req.tenants:
        database.db_provisioning_task_create(
            job_id,
            r.client_id.strip(),
            name=r.name,
            email=r.email,
            area_code=r.area_code,
            plan=r.plan or "free",
        )
    _kick_worker(job_id, req.default_area_code)
    return {"job_id": job_id, "total": len(req.tenants), "status": "running"}


@router.get("/api/admin/provisioning/jobs/{job_id}")
def get_provisioning_job(
    job_id: str,
    admin: str = Depends(deps.require_admin),
):
    job = database.db_provisioning_job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["tasks"] = database.db_provisioning_tasks_for_job(job_id)
    return job


@router.post("/api/admin/provisioning/jobs/{job_id}/resume")
async def resume_provisioning_job(
    job_id: str,
    default_area_code: Optional[str] = None,
    admin: str = Depends(deps.require_admin),
):
    """Re-run a job's pending/failed tasks (idempotent step machine makes this safe)."""
    job = database.db_provisioning_job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _kick_worker(job_id, default_area_code)
    return {"job_id": job_id, "status": "running", "resumed": True}
