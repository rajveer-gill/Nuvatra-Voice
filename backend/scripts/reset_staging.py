"""Reset the STAGING environment to a clean slate.

Releases every REAL provisioned Twilio number (so they stop billing) and then wipes
all tenant data, so you can re-run onboarding from scratch.

DESTRUCTIVE — staging only. Reads Twilio creds + the staging DB URL from the
environment at runtime, so secrets never live in this file or leave your machine.
Refuses to run unless --i-understand-this-wipes-staging is passed AND the DB URL
looks like staging.

  PowerShell (Windows):
    $env:TWILIO_ACCOUNT_SID="ACxxxx"
    $env:TWILIO_AUTH_TOKEN="your_auth_token"
    $env:STAGING_DATABASE_URL="postgresql://...staging..."
    python backend/scripts/reset_staging.py --i-understand-this-wipes-staging
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))


def _require(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        raise SystemExit(f"Missing required env var: {name}")
    return val


def main() -> None:
    ap = argparse.ArgumentParser(description="Wipe staging data + release its Twilio numbers.")
    ap.add_argument("--i-understand-this-wipes-staging", action="store_true")
    args = ap.parse_args()
    if not args.i_understand_this_wipes_staging:
        raise SystemExit("Refusing to run without --i-understand-this-wipes-staging")

    sid = _require("TWILIO_ACCOUNT_SID")
    token = _require("TWILIO_AUTH_TOKEN")
    db_url = _require("STAGING_DATABASE_URL")
    # Safety: never let this point at a non-staging database.
    if "staging" not in db_url:
        raise SystemExit("STAGING_DATABASE_URL does not look like a staging DB — refusing.")

    os.environ["DATABASE_URL"] = db_url
    import database
    import twilio_provision

    database.init_db()
    conn = database._get_conn()
    cur = conn.cursor()
    cur.execute("SELECT client_id, twilio_phone_number, twilio_number_sid FROM tenants")
    rows = cur.fetchall()

    # 1. Release real (provisioned) Twilio numbers so they stop billing. Seed tenants
    #    with placeholder numbers have no number_sid and are skipped.
    released = 0
    for cid, phone, nsid in rows:
        if not nsid:
            continue
        res = twilio_provision.release_number(
            account_sid=sid, auth_token=token, phone_e164=phone or "", number_sid=nsid
        )
        ok = res.get("released")
        released += 1 if ok else 0
        print(f"  release {phone} ({cid}): released={ok} errors={res.get('errors') or 'none'}")

    # 2. Wipe all tenant-scoped data + tenants + memberships.
    for tbl in ("tenant_members", "appointments", "booked_slots", "messages", "call_log", "caller_memory"):
        cur.execute(f"DELETE FROM {tbl}")
    cur.execute("DELETE FROM tenants")
    conn.commit()
    cur.close()

    print(f"\n[OK] Released {released} number(s); wiped {len(rows)} tenant(s) and all related data.")
    print("Staging is a clean slate — sign in and run onboarding from the top.")


if __name__ == "__main__":
    main()
