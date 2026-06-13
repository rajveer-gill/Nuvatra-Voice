#!/usr/bin/env python3
"""
Simulate paid-month Stripe invoices to test the referral commission ledger without
waiting 30 days or using a test clock.

Our /api/stripe-webhook handler processes `invoice.payment_succeeded` purely from the
event payload + the DB (it makes NO Stripe API call for that event), so we can sign and
replay synthetic events to exercise the exact money logic:
  - first paid invoice  -> $200 signup bounty + first 25% commission
  - each later invoice   -> another 25% commission (capped at 12 / within a year)
  - same invoice id twice -> idempotent (no duplicate payout)

PREREQUISITE: a referred signup must already exist with status 'granted'/'converted'
and a real Stripe subscription id. Get that by doing one real test-mode checkout with a
referral code (see the runbook), then grab the subscription id (sub_...) from the Stripe
test dashboard or the referral_redemptions row.

Usage:
  python3 referral_test_webhook.py \
      --url https://YOUR-BACKEND/api/stripe-webhook \
      --secret whsec_xxx \
      --sub sub_123 \
      --months 3            # send 3 monthly paid invoices (in_test_1..3)

  # Idempotency check: re-run with the same --invoice-id and confirm no new payout row.
  python3 referral_test_webhook.py --url ... --secret ... --sub sub_123 --invoice-id in_test_1

The webhook secret is the same STRIPE_WEBHOOK_SECRET your server verifies against
(test-mode secret if you're pointing at a test deployment). Never run this against a
production tenant you care about — it writes real commission rows.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time
import urllib.request


def _sign_and_post(url: str, secret: str, event: dict) -> tuple[int, str]:
    # Send EXACTLY the bytes we sign (Stripe recomputes the HMAC over the raw body).
    payload = json.dumps(event, separators=(",", ":")).encode()
    ts = int(time.time())
    signed = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    header = f"t={ts},v1={sig}"
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Stripe-Signature": header},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return e.code, e.read().decode()


def _invoice_event(sub_id: str, invoice_id: str, amount_cents: int) -> dict:
    return {
        "id": f"evt_{invoice_id}",
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "id": invoice_id,
                "object": "invoice",
                "subscription": sub_id,
                "amount_paid": amount_cents,
                "billing_reason": "subscription_cycle",
            }
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Replay signed invoice.payment_succeeded events.")
    p.add_argument("--url", required=True, help="Webhook URL, e.g. https://host/api/stripe-webhook")
    p.add_argument("--secret", required=True, help="STRIPE_WEBHOOK_SECRET (whsec_...)")
    p.add_argument("--sub", required=True, help="Referred subscription id (sub_...)")
    p.add_argument("--amount", type=int, default=25000, help="amount_paid in cents (default 25000)")
    p.add_argument("--months", type=int, default=1, help="How many monthly invoices to send")
    p.add_argument("--invoice-id", default=None, help="Fixed invoice id (for idempotency tests)")
    p.add_argument("--invoice-prefix", default="in_reftest", help="Prefix for generated invoice ids")
    args = p.parse_args()

    invoice_ids = (
        [args.invoice_id]
        if args.invoice_id
        else [f"{args.invoice_prefix}_{i + 1}" for i in range(args.months)]
    )
    for inv in invoice_ids:
        event = _invoice_event(args.sub, inv, args.amount)
        status, body = _sign_and_post(args.url, args.secret, event)
        ok = status == 200
        print(f"[{'OK' if ok else 'ERR'}] invoice={inv} amount={args.amount} -> {status} {body.strip()[:120]}")
        if not ok:
            print("  (401/400 usually means a wrong --secret; 200 with {'received': true} is success)")
        time.sleep(0.3)
    print("\nDone. Refresh the admin Referrals → Payouts owed panel to see the bounty + commissions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
