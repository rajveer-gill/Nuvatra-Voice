"""Admin: read the audit trail (who did what, when, from where)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

import database
import deps

router = APIRouter()


@router.get("/api/admin/audit")
async def list_audit_events(
    limit: int = 100,
    client_id: Optional[str] = None,
    action: Optional[str] = None,
    _admin: str = Depends(deps.require_admin),
):
    """Recent audit events (admin-only), newest first, with optional filters."""
    return {
        "events": database.db_audit_list(limit=limit, client_id=client_id, action=action)
    }
