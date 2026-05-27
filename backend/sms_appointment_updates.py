"""Parse and persist appointment detail corrections from inbound SMS (name, email)."""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

DetailUpdateResult = Tuple[Optional[dict], list[str]]

from observability import email_hint_for_log, name_initial_for_log, sms_info, sms_trace

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_NAME_PATTERNS = (
    re.compile(r"(?:my\s+)?name\s+is\s+([A-Za-z][A-Za-z'\-\s]{1,48})", re.I),
    re.compile(r"(?:it'?s|i'?m|i am)\s+([A-Za-z][A-Za-z'\-\s]{1,48})(?:\s*,|\s+and\b|\s+not\b|$)", re.I),
    re.compile(r"call\s+me\s+([A-Za-z][A-Za-z'\-\s]{1,48})", re.I),
)


def parse_email_from_sms(body: str) -> Optional[str]:
    m = _EMAIL_RE.search(body or "")
    return m.group(0).strip() if m else None


def _clean_parsed_name(raw: str) -> Optional[str]:
    name = (raw or "").strip()
    name = re.sub(r"[,.\s]+$", "", name)
    name = re.split(r"\s+not\s+", name, maxsplit=1, flags=re.I)[0].strip()
    name = re.split(r"\s+and\s+my\s+", name, maxsplit=1, flags=re.I)[0].strip()
    if len(name) < 2 or len(name) > 50:
        return None
    if not re.match(r"^[A-Za-z]", name):
        return None
    return name


def parse_name_from_sms(body: str, *, current_name: str = "") -> Optional[str]:
    """Best-effort name from correction texts like 'my name is Raj, not Jake'."""
    text = (body or "").strip()
    if not text:
        return None
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            cleaned = _clean_parsed_name(m.group(1))
            if cleaned:
                cur = (current_name or "").strip().lower()
                if cleaned.lower() != cur:
                    return cleaned
    return None


def apply_sms_appointment_detail_updates_from_bodies(
    bodies: list[str],
    apt: Optional[dict],
    *,
    client_id: str,
    from_number: str,
    db_appointments_update,
    db_appointments_get_by_id,
    update_caller_memory,
    db_appointments_update_active_name_by_phone=None,
    system_info,
    logger,
) -> DetailUpdateResult:
    """Apply name/email from the latest values across recent inbound SMS texts."""
    if not apt or not apt.get("id"):
        return apt, []
    st = (apt.get("status") or "").strip()
    if st not in ("pending_customer", "pending_review", "accepted"):
        return apt, []
    aid = int(apt["id"])
    prior_name = (apt.get("name") or "").strip()
    latest_name: Optional[str] = None
    latest_email: Optional[str] = None
    cur_name = prior_name
    user_body_count = sum(1 for b in bodies if (b or "").strip())
    sms_info(
        "sms_detail_updates_scan",
        apt_id=aid,
        client_id=client_id,
        user_body_count=user_body_count,
        prior_name_initial=name_initial_for_log(prior_name),
        apt_status=st,
    )
    for body in bodies:
        if not (body or "").strip():
            continue
        em = parse_email_from_sms(body)
        if em:
            latest_email = em
        nm = parse_name_from_sms(body, current_name=cur_name)
        if nm:
            latest_name = nm
            cur_name = nm
    kwargs: dict[str, Any] = {}
    if latest_email:
        kwargs["email"] = latest_email
    if latest_name:
        kwargs["name"] = latest_name
    if not kwargs:
        sms_info(
            "sms_detail_updates_no_match",
            apt_id=aid,
            client_id=client_id,
            user_body_count=user_body_count,
            prior_name_initial=name_initial_for_log(prior_name),
        )
        return apt, []
    sms_info(
        "sms_detail_updates_parsed",
        apt_id=aid,
        client_id=client_id,
        will_update_name=bool(latest_name),
        will_update_email=bool(latest_email),
        prior_name_initial=name_initial_for_log(prior_name),
        new_name_initial=name_initial_for_log(latest_name),
        email_hint=email_hint_for_log(latest_email),
    )
    return apply_sms_appointment_detail_updates(
        " ".join(bodies),
        apt,
        client_id=client_id,
        from_number=from_number,
        db_appointments_update=db_appointments_update,
        db_appointments_get_by_id=db_appointments_get_by_id,
        update_caller_memory=update_caller_memory,
        db_appointments_update_active_name_by_phone=db_appointments_update_active_name_by_phone,
        system_info=system_info,
        logger=logger,
        _forced_kwargs=kwargs,
    )


def apply_sms_appointment_detail_updates(
    body: str,
    apt: Optional[dict],
    *,
    client_id: str,
    from_number: str,
    db_appointments_update,
    db_appointments_get_by_id,
    update_caller_memory,
    db_appointments_update_active_name_by_phone=None,
    system_info,
    logger,
    _forced_kwargs: Optional[dict[str, Any]] = None,
) -> DetailUpdateResult:
    """
    Persist email/name from SMS before confirm or conversational replies.
    Returns (appointment row, field names that actually changed).
    """
    if not apt or not apt.get("id"):
        return apt, []
    st = (apt.get("status") or "").strip()
    if st not in ("pending_customer", "pending_review", "accepted"):
        return apt, []
    aid = int(apt["id"])
    kwargs: dict[str, Any] = dict(_forced_kwargs or {})
    if not kwargs:
        em = parse_email_from_sms(body)
        if em:
            kwargs["email"] = em
        nm = parse_name_from_sms(body, current_name=(apt.get("name") or ""))
        if nm:
            kwargs["name"] = nm
    if not kwargs:
        return apt, []
    prior = {k: (apt.get(k) or "").strip() for k in kwargs}
    try:
        updated = db_appointments_update(aid, client_id=client_id, **kwargs)
        if not updated:
            return apt, []
        apt = updated
        mem_patch: dict = {}
        if kwargs.get("email"):
            mem_patch["email_on_file"] = kwargs["email"]
        try:
            update_caller_memory(
                from_number,
                name=kwargs.get("name") or (apt.get("name") or "").strip() or None,
                increment_count=False,
                data_patch=mem_patch if mem_patch else None,
            )
        except Exception:
            pass
        refreshed = db_appointments_get_by_id(aid, client_id=client_id) or apt
        system_info(
            "inbound_customer_details_updated_from_sms",
            apt_id=aid,
            client_id=client_id,
            fields=list(kwargs.keys()),
        )
        sms_info(
            "sms_detail_updates_applied",
            apt_id=aid,
            client_id=client_id,
            fields=list(kwargs.keys()),
            name_initial=name_initial_for_log(refreshed.get("name")),
            email_hint=email_hint_for_log(refreshed.get("email")),
        )
        sms_trace(
            "sms_detail_updates_applied_verbose",
            apt_id=aid,
            client_id=client_id,
            fields=list(kwargs.keys()),
            name_initial=name_initial_for_log(refreshed.get("name")),
            email_hint=email_hint_for_log(refreshed.get("email")),
        )
        if kwargs.get("name") and callable(db_appointments_update_active_name_by_phone):
            try:
                updated_n = db_appointments_update_active_name_by_phone(
                    from_number,
                    client_id=client_id,
                    name=kwargs["name"],
                    exclude_appointment_id=aid,
                )
                if updated_n:
                    sms_info(
                        "sms_detail_updates_bulk_name_applied",
                        apt_id=aid,
                        client_id=client_id,
                        updated_rows=updated_n,
                        name_initial=name_initial_for_log(kwargs.get("name")),
                    )
            except Exception:
                pass
        changed = [
            k
            for k in kwargs
            if (refreshed.get(k) or "").strip() != prior.get(k, "")
        ]
        return refreshed, changed
    except Exception as e:
        logger.warning("apply_sms_appointment_detail_updates failed apt_id=%s: %s", aid, e, exc_info=True)
        return apt, []
