"""User feedback API — bug reports and product suggestions from the dashboard.

Any signed-in tenant can submit (intentionally NOT gated on an active subscription, so a
user can still report a billing/access bug). Every submission is stored durably and, when
OPERATOR_ALERT_EMAIL is configured, emailed to the operator best-effort. Listing is
admin-only (ADMIN_CLERK_USER_IDS)."""

from __future__ import annotations

import html
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import database
import deps
import email_notify
import runtime

router = APIRouter()

_CATEGORY_LABELS = {"bug": "🐞 Bug report", "idea": "💡 Suggestion", "other": "💬 Feedback"}


class FeedbackBody(BaseModel):
    category: str = Field("other")
    message: str = Field(..., min_length=1, max_length=4000)
    email: Optional[str] = Field(None, max_length=254)
    page_url: Optional[str] = Field(None, max_length=500)


@router.post("/api/feedback")
def submit_feedback(
    body: FeedbackBody,
    request: Request,
    tenant: Optional[dict] = Depends(deps.require_tenant),
):
    """Store a bug report / suggestion and email the operator (best-effort). Any tenant."""
    category = (body.category or "other").strip().lower()
    if category not in ("bug", "idea", "other"):
        category = "other"
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    cid = deps._bind_tenant_db_context(tenant)
    client_id = None if not cid or cid == "default" else cid
    user_email = (body.email or "").strip() or None
    user_agent = (request.headers.get("user-agent") or "")[:500]
    page_url = (body.page_url or "").strip()[:500]

    feedback_id = (
        database.db_feedback_insert(
            category=category,
            message=message,
            client_id=client_id,
            user_email=user_email,
            page_url=page_url,
            user_agent=user_agent,
        )
        if runtime.USE_DB
        else None
    )

    # Best-effort operator email. No-op when OPERATOR_ALERT_EMAIL / sender aren't configured.
    email_sent = False
    try:
        label = _CATEGORY_LABELS.get(category, _CATEGORY_LABELS["other"])
        subject = f"{label}: {message[:60]}" + ("…" if len(message) > 60 else "")
        who = html.escape(user_email or "(no email given)")
        biz = html.escape(client_id or "(unknown tenant)")
        body_html = (
            f"<p><strong>{html.escape(label)}</strong></p>"
            f"<p><strong>From:</strong> {who}<br>"
            f"<strong>Tenant:</strong> {biz}<br>"
            f"<strong>Page:</strong> {html.escape(page_url or '—')}</p>"
            f"<p style='white-space:pre-wrap'>{html.escape(message)}</p>"
        )
        email_sent = email_notify.send_operator_alert(subject, body_html)
    except Exception:
        email_sent = False

    deps.audit_log(
        "user",
        "feedback_submitted",
        resource_type="feedback",
        resource_id=str(feedback_id) if feedback_id else None,
        client_id=client_id,
        details={"category": category, "email_sent": email_sent, "stored": bool(feedback_id)},
        request=request,
    )
    return {"success": True, "id": feedback_id}


@router.get("/api/feedback")
def list_feedback(
    _admin_user_id: str = Depends(deps.require_admin),
):
    """List all feedback submissions, newest first. Platform-admin only."""
    if not runtime.USE_DB:
        return {"feedback": []}
    return {"feedback": database.db_feedback_get_all(200)}
