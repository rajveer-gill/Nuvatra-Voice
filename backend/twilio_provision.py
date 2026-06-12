"""Twilio IncomingPhoneNumber webhook configuration for tenant numbers."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

_log = logging.getLogger("nuvatra")

try:
    from twilio.rest import Client as TwilioClient
except ImportError:
    TwilioClient = None  # type: ignore[misc, assignment]


def a2p_messaging_service_sid() -> str:
    """The Messaging Service tied to our approved A2P campaign. Numbers added to it
    inherit the campaign (so SMS is A2P-registered) and the service's inbound webhook.
    Empty when unset — enrollment then no-ops, leaving existing flows unchanged."""
    return (os.getenv("TWILIO_A2P_MESSAGING_SERVICE_SID") or "").strip()


def _number_in_messaging_service(client: Any, messaging_service_sid: str, number_sid: str) -> bool:
    """True if the IncomingPhoneNumber SID is already in the service's sender pool."""
    try:
        for pn in client.messaging.v1.services(messaging_service_sid).phone_numbers.list(limit=400):
            if getattr(pn, "sid", None) == number_sid:
                return True
    except Exception:
        pass
    return False


def enroll_in_messaging_service(client: Any, number_sid: Optional[str]) -> dict[str, Any]:
    """Add a purchased/configured number to the A2P Messaging Service sender pool so it
    inherits the approved campaign. No-op (skipped=True) when the service SID is unset.
    Never fatal — a number can still answer calls and send unregistered if this fails."""
    out: dict[str, Any] = {"enrolled": False, "skipped": False, "errors": []}
    msid = a2p_messaging_service_sid()
    if not msid:
        out["skipped"] = True
        return out
    if not number_sid:
        out["errors"].append("messaging_service_enroll_missing_number_sid")
        return out
    try:
        client.messaging.v1.services(msid).phone_numbers.create(phone_number_sid=number_sid)
        out["enrolled"] = True
    except Exception as e:
        # Idempotent: if it's already in our service, treat as enrolled.
        if _number_in_messaging_service(client, msid, number_sid):
            out["enrolled"] = True
        else:
            out["errors"].append("messaging_service_enroll_failed")
            _log.warning(
                "twilio_messaging_service_enroll_failed number_sid=%s code=%s err=%s",
                number_sid,
                getattr(e, "code", None),
                type(e).__name__,
            )
    return out

VERIFY_CACHE_TTL_SEC = 300
_verify_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def normalize_e164(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if digits and not (phone or "").strip().startswith("+"):
        return f"+{digits}"
    return (phone or "").strip()


def validate_public_base_url(base_url: str) -> tuple[str, list[str]]:
    """
    Validate PUBLIC_BASE_URL: HTTPS origin only (no path, query, credentials).
    Returns (normalized_origin, client_safe_error_codes).
    """
    errors: list[str] = []
    raw = (base_url or "").strip()
    if not raw:
        return "", ["public_base_url_missing"]
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        errors.append("public_base_url_must_be_https")
    if parsed.username or parsed.password:
        errors.append("public_base_url_must_not_include_credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        errors.append("public_base_url_must_be_origin_only")
    if not parsed.netloc:
        errors.append("public_base_url_invalid_host")
    if errors:
        return "", errors
    return f"https://{parsed.netloc}".rstrip("/"), []


def _expected_webhook_urls(base_url: str) -> dict[str, str]:
    bu = base_url.rstrip("/")
    return {
        "voice": f"{bu}/api/phone/incoming",
        "sms": f"{bu}/api/sms/incoming",
        "status": f"{bu}/api/phone/status",
    }


def find_incoming_number(client: Any, phone: str) -> Optional[Any]:
    """Find IncomingPhoneNumber resource in the Twilio account."""
    target = normalize_e164(phone)
    target_digits = re.sub(r"\D", "", target)
    try:
        numbers = client.incoming_phone_numbers.list(phone_number=target, limit=1)
        if numbers:
            return numbers[0]
        for num in client.incoming_phone_numbers.list(limit=200):
            listed = normalize_e164(getattr(num, "phone_number", "") or "")
            if re.sub(r"\D", "", listed) == target_digits:
                return num
    except Exception as e:
        _log.warning("twilio_find_incoming_number_failed err=%s", type(e).__name__)
    return None


def public_webhook_result(result: dict[str, Any]) -> dict[str, Any]:
    """Strip internal details before returning webhook config to clients."""
    return {
        "voice_ok": bool(result.get("voice_ok")),
        "sms_ok": bool(result.get("sms_ok")),
        "status_ok": bool(result.get("status_ok")),
        "errors": list(result.get("errors") or []),
        "phone_e164": result.get("phone_e164"),
        "number_sid": result.get("number_sid"),
        "messaging_service_enrolled": bool(result.get("messaging_service_enrolled")),
    }


def configure_webhooks(
    *,
    account_sid: str,
    auth_token: str,
    phone: str,
    base_url: str,
) -> dict[str, Any]:
    """
    Set Voice, SMS, and status callback URLs on an existing Twilio number.
    Returns { voice_ok, sms_ok, status_ok, errors, phone_e164, number_sid }.
    """
    result: dict[str, Any] = {
        "voice_ok": False,
        "sms_ok": False,
        "status_ok": False,
        "errors": [],
        "phone_e164": normalize_e164(phone),
        "number_sid": None,
        "messaging_service_enrolled": False,
    }
    base, base_errors = validate_public_base_url(base_url)
    if base_errors:
        result["errors"].extend(base_errors)
        return result
    if not account_sid or not auth_token:
        result["errors"].append("twilio_credentials_required")
        return result
    if TwilioClient is None:
        result["errors"].append("twilio_sdk_unavailable")
        return result

    urls = _expected_webhook_urls(base)
    try:
        client = TwilioClient(account_sid, auth_token)
        number = find_incoming_number(client, phone)
        if not number:
            result["errors"].append("twilio_number_not_in_account")
            return result
        result["number_sid"] = getattr(number, "sid", None)
        number.update(
            voice_url=urls["voice"],
            voice_method="POST",
            sms_url=urls["sms"],
            sms_method="POST",
            status_callback=urls["status"],
            status_callback_method="POST",
        )
        result["voice_ok"] = True
        result["sms_ok"] = True
        result["status_ok"] = True
        enroll = enroll_in_messaging_service(client, result["number_sid"])
        result["messaging_service_enrolled"] = enroll["enrolled"]
        result["errors"].extend(enroll["errors"])
        _verify_cache.pop(_verify_cache_key(account_sid, phone, base), None)
    except Exception as e:
        result["errors"].append("twilio_configure_failed")
        _log.warning(
            "twilio_configure_webhooks_failed phone=%s err=%s",
            result["phone_e164"],
            type(e).__name__,
        )
    return result


def purchase_number(
    *,
    account_sid: str,
    auth_token: str,
    base_url: str,
    area_code: Optional[str] = None,
    country: str = "US",
) -> dict[str, Any]:
    """Search available local numbers and buy one, configuring webhooks at purchase.

    Used by bulk onboarding. Idempotency (don't buy twice for a tenant) is the
    caller's responsibility — this just provisions one number. Returns
    { ok, phone_e164, number_sid, errors }.
    """
    result: dict[str, Any] = {
        "ok": False,
        "phone_e164": None,
        "number_sid": None,
        "errors": [],
        "messaging_service_enrolled": False,
    }
    base, base_errors = validate_public_base_url(base_url)
    if base_errors:
        result["errors"].extend(base_errors)
        return result
    if not account_sid or not auth_token:
        result["errors"].append("twilio_credentials_required")
        return result
    if TwilioClient is None:
        result["errors"].append("twilio_sdk_unavailable")
        return result

    urls = _expected_webhook_urls(base)
    try:
        client = TwilioClient(account_sid, auth_token)
        search_kwargs: dict[str, Any] = {"limit": 1}
        if area_code:
            search_kwargs["area_code"] = re.sub(r"\D", "", str(area_code))[:3]
        available = client.available_phone_numbers(country).local.list(**search_kwargs)
        if not available:
            result["errors"].append("no_available_numbers")
            return result
        chosen = getattr(available[0], "phone_number", None)
        if not chosen:
            result["errors"].append("no_available_numbers")
            return result
        purchased = client.incoming_phone_numbers.create(
            phone_number=chosen,
            voice_url=urls["voice"],
            voice_method="POST",
            sms_url=urls["sms"],
            sms_method="POST",
            status_callback=urls["status"],
            status_callback_method="POST",
        )
        result["ok"] = True
        result["phone_e164"] = normalize_e164(
            getattr(purchased, "phone_number", chosen) or chosen
        )
        result["number_sid"] = getattr(purchased, "sid", None)
        enroll = enroll_in_messaging_service(client, result["number_sid"])
        result["messaging_service_enrolled"] = enroll["enrolled"]
        result["errors"].extend(enroll["errors"])
    except Exception as e:
        result["errors"].append("twilio_purchase_failed")
        _log.warning(
            "twilio_purchase_number_failed area=%s err=%s",
            area_code,
            type(e).__name__,
        )
    return result


def verify_webhooks_match(
    *,
    account_sid: str,
    auth_token: str,
    phone: str,
    base_url: str,
) -> dict[str, Any]:
    """Check whether configured webhooks match expected URLs (best-effort)."""
    out: dict[str, Any] = {
        "webhooks_configured": False,
        "voice_ok": False,
        "sms_ok": False,
        "status_ok": False,
        "errors": [],
    }
    base, base_errors = validate_public_base_url(base_url)
    if base_errors or not account_sid or not auth_token or TwilioClient is None:
        if base_errors:
            out["errors"].extend(base_errors)
        return out
    expected = _expected_webhook_urls(base)
    try:
        client = TwilioClient(account_sid, auth_token)
        number = find_incoming_number(client, phone)
        if not number:
            out["errors"].append("twilio_number_not_in_account")
            return out
        out["voice_ok"] = (getattr(number, "voice_url", "") or "").rstrip("/") == expected["voice"]
        out["sms_ok"] = (getattr(number, "sms_url", "") or "").rstrip("/") == expected["sms"]
        out["status_ok"] = (getattr(number, "status_callback", "") or "").rstrip("/") == expected["status"]
        out["webhooks_configured"] = out["voice_ok"] and out["sms_ok"] and out["status_ok"]
    except Exception as e:
        out["errors"].append("twilio_verify_failed")
        _log.warning("twilio_verify_webhooks_failed phone=%s err=%s", normalize_e164(phone), type(e).__name__)
    return out


def _verify_cache_key(account_sid: str, phone: str, base_url: str) -> str:
    return f"{account_sid}:{normalize_e164(phone)}:{base_url.rstrip('/')}"


def verify_webhooks_match_cached(
    *,
    account_sid: str,
    auth_token: str,
    phone: str,
    base_url: str,
    ttl_sec: int = VERIFY_CACHE_TTL_SEC,
) -> dict[str, Any]:
    """Cached wrapper for setup-status checks (avoids Twilio API on every dashboard load)."""
    base, base_errors = validate_public_base_url(base_url)
    if base_errors:
        return {"webhooks_configured": False, "voice_ok": False, "sms_ok": False, "status_ok": False, "errors": base_errors}
    key = _verify_cache_key(account_sid, phone, base)
    now = time.monotonic()
    cached = _verify_cache.get(key)
    if cached and now - cached[0] < ttl_sec:
        return cached[1]
    result = verify_webhooks_match(
        account_sid=account_sid,
        auth_token=auth_token,
        phone=phone,
        base_url=base,
    )
    _verify_cache[key] = (now, result)
    return result


def reset_webhook_verify_cache_for_tests() -> None:
    _verify_cache.clear()
