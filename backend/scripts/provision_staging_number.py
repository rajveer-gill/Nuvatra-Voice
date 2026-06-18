"""Buy a Twilio number for a STAGING test tenant and wire its webhooks to staging.

Uses the app's real provisioning (twilio_provision.purchase_number), which buys an
available local number AND configures its voice/SMS webhooks at purchase time —
pointed at the staging backend. Then assigns the number to the test tenant. It does
NOT touch the tenant's business config (unlike the bulk onboarding path).

Secrets are read from the environment at runtime — nothing sensitive is stored in
this file. Run it yourself so your Twilio credentials never leave your machine:

  PowerShell (Windows):
    $env:TWILIO_ACCOUNT_SID="ACxxxx"
    $env:TWILIO_AUTH_TOKEN="your_auth_token"
    $env:STAGING_DATABASE_URL="postgresql://...staging..."
    python backend/scripts/provision_staging_number.py

  bash:
    TWILIO_ACCOUNT_SID=ACxxxx TWILIO_AUTH_TOKEN=xxx STAGING_DATABASE_URL=postgresql://... \
      python backend/scripts/provision_staging_number.py

Optional env: STAGING_BASE_URL (defaults to the staging backend), CLIENT_ID
(defaults to seed-test-autobody), AREA_CODE.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

DEFAULT_BASE_URL = "https://nuvatra-voice-backend-staging.onrender.com"
DEFAULT_CLIENT_ID = "seed-test-autobody"


def _require(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        raise SystemExit(f"Missing required env var: {name}")
    return val


def main() -> None:
    sid = _require("TWILIO_ACCOUNT_SID")
    token = _require("TWILIO_AUTH_TOKEN")
    db_url = _require("STAGING_DATABASE_URL")
    base_url = (os.getenv("STAGING_BASE_URL") or DEFAULT_BASE_URL).strip()
    client_id = (os.getenv("CLIENT_ID") or DEFAULT_CLIENT_ID).strip()
    area_code = (os.getenv("AREA_CODE") or "").strip() or None

    # Safety: only operate on disposable seed tenants unless explicitly forced.
    if not client_id.startswith("seed-test-") and os.getenv("FORCE") != "1":
        raise SystemExit(
            f"Refusing: {client_id!r} is not a seed-test tenant. Set FORCE=1 to override."
        )

    # Point the DB at staging (the script never reads the local .env DATABASE_URL).
    os.environ["DATABASE_URL"] = db_url
    os.environ["PUBLIC_BASE_URL"] = base_url  # webhook URLs derive from this

    import database
    import twilio_provision

    database.init_db()
    tenant = database.db_tenant_get_by_client_id(client_id)
    if not tenant:
        raise SystemExit(f"Tenant {client_id!r} not found in the target database.")

    print(f"Buying a Twilio number and pointing its webhooks at {base_url} ...")
    res = twilio_provision.purchase_number(
        account_sid=sid, auth_token=token, base_url=base_url, area_code=area_code
    )
    if not res.get("ok"):
        raise SystemExit("Purchase failed: " + ", ".join(res.get("errors") or ["unknown"]))

    phone = res["phone_e164"]
    number_sid = res.get("number_sid")
    database.db_tenant_set_twilio_phone(tenant["id"], phone)
    if number_sid:
        database.db_tenant_set_twilio_number_sid(tenant["id"], number_sid)

    print(f"[OK] Provisioned {phone} -> {client_id}")
    print(f"     voice + SMS webhooks configured to {base_url}")
    print(f"     messaging service enrolled: {res.get('messaging_service_enrolled')}")
    print("Call this number to test the auto-body flow.")


if __name__ == "__main__":
    main()
