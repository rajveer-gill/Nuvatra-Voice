# Production environment checklist

Single reference for **Call Surge / Nuvatra Voice** production variables. Canonical domains:

| Role | URL |
|------|-----|
| Frontend (Vercel) | `https://www.call-surge.com` |
| Backend (Render) | `https://nuvatra-voice.onrender.com` |
| Clerk Frontend API | `https://clerk.call-surge.com` |

See also [CLERK-JWT-SETUP.md](./CLERK-JWT-SETUP.md), [DEPLOYMENT.md](../DEPLOYMENT.md), and [render.yaml](../render.yaml).

---

## Render — web service (`nuvatra-voice-backend`)

### Required

| Variable | Example / notes |
|----------|-----------------|
| `DATABASE_URL` | Linked from Render Postgres (Virginia) |
| `REDIS_URL` | Linked from Render Redis (voice call state). **Network:** keep Redis private to the backend service only (Render internal URL; do not expose Redis to the public internet or allow `0.0.0.0/0`). Voice session keys hold caller metadata — treat compromise of Redis as PII exposure. **Audit:** [REDIS-SECURITY.md](./REDIS-SECURITY.md). **Production gate:** Admin → Ops → **Redis production ready** must be green before `VOICE_STT_PROVIDER=deepgram`. |
| `OPENAI_API_KEY` | Real OpenAI key |
| `PUBLIC_BASE_URL` | `https://nuvatra-voice.onrender.com` (no trailing slash) |
| `FRONTEND_URL` | `https://www.call-surge.com` |
| `CLERK_JWKS_URL` | `https://clerk.call-surge.com/.well-known/jwks.json` |
| `CLERK_ISSUER` | `https://clerk.call-surge.com` |
| `CLERK_AUDIENCE` | `https://nuvatra-voice.onrender.com` (matches JWT template `aud`) |
| `CLERK_SECRET_KEY` | Clerk secret (admin invites) |
| `ADMIN_CLERK_USER_IDS` | Comma-separated Clerk user IDs |
| `TWILIO_ACCOUNT_SID` | Twilio account |
| `TWILIO_AUTH_TOKEN` | Enables webhook signature validation |
| `STRIPE_SECRET_KEY` | Billing |
| `STRIPE_WEBHOOK_SECRET` | `/api/stripe-webhook` |
| `STRIPE_STARTER_PRICE_ID` | Stripe price IDs |
| `STRIPE_GROWTH_PRICE_ID` | |
| `STRIPE_PRO_PRICE_ID` | |
| `CRON_SECRET` | Shared with Render cron jobs (`X-Cron-Secret`) |

### Do not set in multi-tenant production

| Variable | Why |
|----------|-----|
| `CLIENT_ID` | Forces wrong tenant config from disk |
| `ALLOW_INSECURE_WEBHOOKS` | Disables Twilio signature checks |

### Recommended optional

| Variable | Purpose |
|----------|---------|
| `SENTRY_DSN` | Backend error tracking |
| `SENTRY_ENVIRONMENT` | `production` |
| `SENTRY_TRACES_SAMPLE_RATE` | Default `0.1` (10% traces) |
| `VOICE_STT_PROVIDER` | `deepgram` for Nova-2 streaming (requires Redis) |
| `DEEPGRAM_API_KEY` | Required when STT provider is `deepgram` |
| `CALL_RECORDING_ENABLED` | `true` for dual-channel recording |
| `REMINDER_TIMEZONE` | e.g. `America/New_York` |
| `OVERAGE_PRICE_PER_MINUTE` | e.g. `0.15` |
| `LOG_LEVEL` | `INFO` (use `DEBUG` + `OBS_*` only when debugging) |

---

## Render — cron jobs

Four cron services in [render.yaml](../render.yaml). Each needs the same `CRON_SECRET` and `PUBLIC_BASE_URL` as the web service.

Verify runs in **Admin → Ops** panel (`last_cron_runs`) or Render logs.

---

## Vercel — frontend

| Variable | Value |
|----------|--------|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk publishable key |
| `CLERK_SECRET_KEY` | Clerk secret |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | `/sign-in` |
| `NEXT_PUBLIC_CLERK_SIGN_UP_URL` | `/sign-up` |
| `NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL` | `/dashboard` |
| `NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL` | `/dashboard` |
| `NEXT_PUBLIC_CLERK_JWT_TEMPLATE` | `nuvatra-backend` |
| `NEXT_PUBLIC_API_URL` | `https://nuvatra-voice.onrender.com` |
| `ADMIN_CLERK_USER_IDS` | Same as backend |
| `NEXT_PUBLIC_SENTRY_DSN` | Optional browser errors |
| `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | `production` |
| `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | `0.1` |

Remove deprecated `NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL` / `AFTER_SIGN_UP_URL` if still set.

---

## External monitoring (manual)

Configure uptime checks (Better Stack, Checkly, etc.) every 5 minutes:

- `GET https://nuvatra-voice.onrender.com/api/health` → 200, `"database":"ok"`
- `GET https://www.call-surge.com` → 200
- `GET https://clerk.call-surge.com/.well-known/jwks.json` → 200

After deploy, run `./scripts/post-deploy-smoke.sh`.

---

## Post-deploy verification

1. Admin → **Ops** panel: all checks green (including **Redis production ready** — see [REDIS-SECURITY.md](./REDIS-SECURITY.md))
2. Sign in → Dashboard + Settings load
3. One test call → booking + confirmation SMS
4. Grep Render logs for `booking_created_pending_customer`

See [post-deploy-verification.md](./post-deploy-verification.md).
