# Post-deploy verification (Call-Surge / Nuvatra Voice)

Use this after hardening deploy and Clerk JWT setup (`CLERK_ISSUER`, `CLERK_AUDIENCE`, JWT template). Paste the prompt below into Claude Chrome (or run manually).

---

## Chrome / agent prompt

```text
Run a production readiness verification on Call-Surge backend after hardening deploy.

Security checks (no secrets in output):
1) Confirm env vars present (names only): CLERK_JWKS_URL, CLERK_ISSUER, CLERK_AUDIENCE, TWILIO_AUTH_TOKEN, ALLOW_INSECURE_WEBHOOKS
2) Confirm latest deploy commit includes ef002da (or newer hardening commit)
3) GET /api/health -> expect status ok

Auth/webhook behavior checks:
4) Confirm dashboard login works (user can access protected pages)
5) In Render logs during one test call, grep for:
   - tenant_resolved_by_to_number
   - voice_booking_line_parsed
   - booking_created_pending_customer
   - post_booking_confirmation_sms
   - voice_booking_not_created (should NOT appear on successful booking)
   - webhook signature invalid (should NOT appear for real Twilio traffic)
   - tenant_not_resolved (should NOT appear for known business number)

Negative tests (safe):
6) Report whether invalid Twilio signature would be rejected (theory from code path; do not expose signature)
7) Report whether unknown To number is rejected/no-op (no CLIENT_ID/default fallback)

Return a short pass/fail table and top 3 actions if anything fails.
```

---

## Manual quick checks

- **Health:** `curl -s https://nuvatra-voice.onrender.com/api/health`
- **JWKS:** `curl -sI https://clerk.call-surge.com/.well-known/jwks.json` → HTTP 200
- **Dashboard:** sign in → Appointments + Settings load without 401/500
- **Voice test:** one booking call → Render logs show `booking_created_pending_customer` and SMS send

See also [`CLERK-JWT-SETUP.md`](./CLERK-JWT-SETUP.md) for auth configuration.
