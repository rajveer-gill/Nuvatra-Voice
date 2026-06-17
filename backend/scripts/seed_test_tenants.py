"""Seed disposable test tenants for staging / local GUI testing.

The hard part of testing the dashboard (Settings, industry dropdown, booking) is
that it needs a real tenant row you're allowed to break. This script creates two
— one salon, one auto body — with realistic services/staff/hours, marked
billing-exempt so they never expire.

Run it against a STAGING database (or a throwaway local one) — never production.
It refuses to run unless --i-understand-this-writes-data is passed, and it
deletes + recreates the test tenants each run (idempotent).

Usage (from backend/):
    python scripts/seed_test_tenants.py --i-understand-this-writes-data
    # link them to your Clerk user so you land on them when you log in:
    python scripts/seed_test_tenants.py --i-understand-this-writes-data --clerk-user user_xxx

The --clerk-user value is your Clerk user id (Clerk dashboard → Users → the id
starting with "user_"). Linking lets you sign in and immediately see the tenant
in the dashboard. Only one tenant can be your "single" membership at a time, so
the LAST tenant seeded wins the link (auto body, so you can test it directly).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make the backend package importable when run as `python scripts/seed_test_tenants.py`.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND_DIR / ".env", override=True)

import config_service  # noqa: E402
import database  # noqa: E402


# Each spec produces one tenant. client_ids are prefixed so they're obvious test
# data and easy to purge. Phones are Twilio "magic" test-style placeholders.
TEST_TENANTS = [
    {
        "client_id": "seed-test-salon",
        "name": "Seed Test Salon",
        "phone": "+15005550101",
        "vertical": "salon_chair",
        "config": {
            "hours": "Tue-Sat 9am-6pm",
            "address": "123 Main St, Springfield",
            "receptionist_name": "Riley",
            "services": [
                {"id": "svc-shortcut", "name": "Short Cut", "price": 35, "duration_minutes": 30},
                {"id": "svc-longcut", "name": "Long Cut", "price": 55, "duration_minutes": 45},
                {"id": "svc-color", "name": "Color", "price": 120, "duration_minutes": 90},
            ],
            "staff": [
                {"id": "stf-jamie", "name": "Jamie", "service_ids": ["svc-shortcut", "svc-longcut"]},
                {"id": "stf-alex", "name": "Alex", "service_ids": []},
            ],
        },
    },
    {
        "client_id": "seed-test-autobody",
        "name": "Seed Test Auto Body",
        "phone": "+15005550102",
        "vertical": "auto_body",
        "config": {
            "hours": "Mon-Fri 8am-5pm",
            "address": "456 Industrial Way, Springfield",
            "receptionist_name": "Sam",
            "services": [
                {"id": "svc-estimate", "name": "Collision Estimate", "price": 0, "duration_minutes": 30},
                {"id": "svc-dent", "name": "Dent Repair", "price": 150, "duration_minutes": 60},
                {"id": "svc-paint", "name": "Paint Job", "price": 800, "duration_minutes": 240},
            ],
            # Auto body books to the shop, not a named technician — realistic
            # config has no roster (the vertical no longer requires one).
            "staff": [],
        },
    },
]


def _is_production_db() -> bool:
    """Best-effort guard: refuse if the DB looks like the real one (has non-seed tenants)."""
    try:
        conn = database._get_conn()
        if not conn:
            return False
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM tenants WHERE client_id NOT LIKE 'seed-test-%%' AND client_id NOT LIKE 'zz-%%'"
        )
        n = cur.fetchone()[0]
        cur.close()
        return n > 0
    except Exception:
        # If we can't tell, fail safe (treat as production).
        return True


def seed_one(spec: dict, clerk_user: str | None) -> None:
    cid = spec["client_id"]
    # Idempotent: drop any prior row so reruns are clean.
    conn = database._get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM tenants WHERE client_id = %s", (cid,))
    conn.commit()
    cur.close()

    tenant = database.db_tenant_create(cid, spec["name"], spec["phone"], "starter", spec["vertical"])
    if not tenant:
        raise SystemExit(f"  [FAIL] failed to create {cid}")

    # Never-expiring so the test tenant always "can use the app".
    far_future = datetime.now(timezone.utc) + timedelta(days=3650)
    database.db_tenant_set_billing_exempt(tenant["id"], far_future)

    # Build + persist the business config (services, staff, hours, etc.).
    cfg = config_service._default_client_config_data(cid, "starter")
    cfg["name"] = spec["name"]
    cfg["phone"] = spec["phone"]
    cfg.update(spec["config"])
    config_service.save_raw_client_config(cid, cfg)

    linked = ""
    if clerk_user:
        if database.db_tenant_member_set_single(clerk_user, tenant["id"]):
            linked = f" (linked to {clerk_user})"
    print(f"  [OK] {cid:<20} vertical={spec['vertical']:<12} staff={len(spec['config']['staff'])}{linked}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed disposable test tenants (staging only).")
    ap.add_argument(
        "--i-understand-this-writes-data",
        action="store_true",
        help="Required acknowledgement that this writes tenant rows.",
    )
    ap.add_argument("--clerk-user", default=None, help="Clerk user id (user_...) to link the tenants to.")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Override the production-DB safety check (dangerous).",
    )
    args = ap.parse_args()

    if not args.i_understand_this_writes_data:
        raise SystemExit("Refusing to run without --i-understand-this-writes-data")

    database.init_db()

    if _is_production_db() and not args.force:
        raise SystemExit(
            "[FAIL] This database contains non-seed tenants — it looks like PRODUCTION.\n"
            "  Point DATABASE_URL at a staging/throwaway DB, or pass --force if you are certain."
        )

    print(f"Seeding {len(TEST_TENANTS)} test tenants...")
    for spec in TEST_TENANTS:
        seed_one(spec, args.clerk_user)
    print("Done. These are billing-exempt and safe to break. Re-run anytime to reset them.")


if __name__ == "__main__":
    main()
