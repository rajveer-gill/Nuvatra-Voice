# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Nuvatra Voice is an AI voice receptionist SaaS with two services:
- **Frontend**: Next.js 14 (TypeScript/React/Tailwind) — deployed on Vercel (e.g. `nuvatra-voice.vercel.app`)
- **Backend**: Python FastAPI — deployed on Render at `nuvatra-voice.onrender.com`

See `README.md` for standard commands (`npm run dev`, `npm run dev:frontend`, `npm run dev:backend`, `npm run lint`, `npm run build`).

### Running services locally

**Backend** (`cd backend && python3 main.py`):
- Requires `backend/.env` with `OPENAI_API_KEY`. Use a placeholder (`sk-placeholder-for-dev-environment`) to start the server without a real key; the pre-warm step will fail gracefully. AI conversation endpoints require a real key.
- Use `python3` not `python` (only `python3` is on PATH in this environment).
- Twilio and PostgreSQL are optional for basic dev; the backend falls back to in-memory storage and disables phone features when credentials are absent.
- For multi-tenant/admin features, PostgreSQL is required. Start it with `sudo pg_ctlcluster 16 main start` and set `DATABASE_URL` in `backend/.env`.

**Frontend** (`npx next dev --hostname 0.0.0.0 --port 3000 --turbo`):
- Clerk authentication is used for `/dashboard` and `/admin` routes. Without real Clerk keys, remove `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` from `.env.local` to enable Clerk's keyless/dev mode (temporary dev keys).
- The `.env.local` must have `NEXT_PUBLIC_API_URL=http://localhost:8000` for frontend-to-backend communication.
- `next build` will fail without valid Clerk keys (static page generation requires them). Dev mode (`next dev`) works fine.

### Production environment

| Service | Host | Env vars location |
|---|---|---|
| Frontend | Vercel (e.g. `nuvatra-voice.vercel.app`) | Vercel dashboard > Project > Environment Variables |
| Backend | Render (`nuvatra-voice.onrender.com`) | Render dashboard > Environment tab |
| Database | Render PostgreSQL (Virginia region) | Auto-linked via `DATABASE_URL` on Render |

Key env vars for production backend (Render): `OPENAI_API_KEY`, `DATABASE_URL`, `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `ADMIN_CLERK_USER_IDS`, `FRONTEND_URL`, **`PUBLIC_BASE_URL`** (canonical HTTPS origin of this API, e.g. `https://nuvatra-voice.onrender.com` — no trailing slash). Twilio `<Play>` / webhook URLs use this when set; the app can still derive from `Host` / `X-Forwarded-*` if unset, but **setting it is recommended** for stable integrations and ops clarity.

**Do not set `CLIENT_ID` on multi-tenant production** unless you run a true single-tenant instance. If `CLIENT_ID` is set to a dev value like `test`, any code path that runs before `require_tenant` sets the request context (or background jobs) will look for `clients/test/config.json` on disk and merge the wrong tenant. Leave `CLIENT_ID` **unset** on Render when using Clerk + PostgreSQL for all tenants.

Key env vars for production frontend (Vercel): `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_API_URL`. Set **`ADMIN_CLERK_USER_IDS`** on Vercel too (same comma-separated Clerk user IDs as the backend) so server layouts route platform admins to `/admin` and everyone else to `/dashboard`; when omitted, the client still checks `/api/admin/session`.

Also set **`NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in`** and **`NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up`** so Clerk uses the embedded routes (`app/sign-in`, `app/sign-up`) instead of only the hosted Account Portal. In **Clerk Dashboard → Paths**, align application paths with those URLs.

For post-login redirects, prefer **`NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL`** and **`NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL`** (see `.env.local.example`). Remove legacy **`NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL`** / **`NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL`** from Vercel once migrated—Clerk still reads those deprecated env names and may warn in the browser console until they are deleted.

After pushing git changes, trigger a **Vercel redeploy** if Production did not pick up the latest commit (dashboard relies on the Next.js **`/api/admin/session`** proxy and **`sameOriginApiConfig`** in `lib/api.ts`).

Optional but common for Call Surge production: `NEXT_PUBLIC_CLERK_JS_URL` (CDN fallback if the Clerk Frontend API subdomain is unhealthy—see below).

### Sign-in / sign-up (email, password, Google, Facebook, Microsoft)

The app embeds Clerk **`<SignIn />`** and **`<SignUp />`** on `/sign-in` and `/sign-up` with a dark theme (`@clerk/themes`). Which methods appear is controlled entirely in **Clerk Dashboard** (not in code):

1. **User & Authentication** → enable **Email address** (and **Password** if you want username/password).
2. **User & Authentication** → **Social connections**: turn on **Google**, **Facebook**, **Microsoft** (and complete each provider’s OAuth setup — Clerk shows redirect URIs to paste into Google Cloud Console, Meta for Developers, Microsoft Entra ID).
3. **Production** OAuth apps must use **your own** client IDs/secrets (Clerk’s dev credentials are not for production).

If the instance remains **invite-only**, new sign-ups may still be restricted by Clerk settings even though the UI lists social and password options—align product policy with Dashboard configuration.

### Clerk Frontend API subdomain (`clerk.<domain>`) — fix 503 / `failed_to_load_clerk_js`

The browser loads `@clerk/clerk-js` from your **Clerk Frontend API host** (e.g. `https://clerk.call-surge.com/npm/@clerk/clerk-js@…/dist/clerk.browser.js`). If that host returns **503** or fails DNS/TLS, Clerk’s SDK will not initialize (`failed_to_load_clerk_js`). A **temporary** mitigation is `NEXT_PUBLIC_CLERK_JS_URL` pointing at a public **jsDelivr** URL for the same major `clerk-js` version; the **durable** fix is to restore Clerk’s own hostname.

Do this in order (human steps—cannot be done from git alone):

1. **Clerk Dashboard** → **Domains** (production instance): open [Domains](https://dashboard.clerk.com/~/domains). Find the **Frontend API** / DNS section and note every record Clerk expects (usually a **CNAME** for `clerk` → Clerk’s target). Use **exact** names and targets—do not invent values.

2. **DNS provider** (where `call-surge.com` is hosted): add or correct those records. If you use **Cloudflare**, set the Frontend API / `clerk` record to **DNS only** (grey cloud), **not** proxied—Clerk’s validation and TLS issuance break when the hostname is orange-clouded to a generic edge IP. Clerk documents this under production troubleshooting (“DNS records not propagating with Cloudflare”).

3. **Wait** for propagation and for Clerk’s dashboard to show the domain / Frontend API as **verified** (can take minutes to hours).

4. **Verify** before removing the CDN workaround: in a browser or with `curl -I`, request the Clerk JS URL on **`https://clerk.call-surge.com/.../clerk.browser.js`** and confirm **HTTP 200** (not 503).

5. **Vercel**: remove **`NEXT_PUBLIC_CLERK_JS_URL`** from Production (and Preview if set), **Redeploy**, then reload `https://www.call-surge.com` and confirm the console no longer needs the jsDelivr URL and Clerk still loads.

6. If TLS never completes, check **CAA records** on the apex domain—Clerk needs Let’s Encrypt or Google Trust Services allowed (see Clerk production deployment troubleshooting).

### Voice call recording (Twilio)

- `CALL_RECORDING_ENABLED` — set to `true` on Render to start dual-channel full-call recording on inbound Twilio calls and to append a spoken disclosure to the greeting (“This call may be recorded for quality and training.”). Requires a public API base URL (`PUBLIC_BASE_URL` on production, or `NGROK_URL` in dev) so Twilio can reach `/api/phone/recording-complete`.
- `CALL_SUMMARY_ENABLED` — optional. If unset, defaults to the same as `CALL_RECORDING_ENABLED` (summaries on when recording is on). Set to `false` to disable post-call Whisper + GPT summaries and avoid that cost in dev.
- `CALL_SUMMARY_MAX_DURATION_SEC` — optional cap (default `1800`); longer recordings skip summarization.
- `TWILIO_INTELLIGENCE_SERVICE_SID` — optional; if set, logs that Intelligence is configured but Phase 1 still uses OpenAI for transcription/summary.

### Voice streaming STT (Deepgram Nova-2, optional)

- Default is Twilio `<Gather input="speech">` (`VOICE_STT_PROVIDER` unset or `twilio`).
- Set **`VOICE_STT_PROVIDER=deepgram`** on Render to use **Twilio `<Connect><Stream>` → `wss://…/api/phone/media`** bridged to **Deepgram Nova-2** live transcription (8 kHz mu-law). When the media WebSocket closes, Twilio continues to the queued **got-it** audio and **`/api/phone/respond`** polling, matching the Gather path.
- **`DEEPGRAM_API_KEY`** — required for the Deepgram path (Render secret; never log or expose client-side).
- **`MEDIA_STREAM_SIGNING_SECRET`** — optional HMAC secret for stream URL tokens; if unset, **`TWILIO_AUTH_TOKEN`** is used for signing (must be set for the Deepgram path to activate).
- **`PUBLIC_BASE_URL`** (HTTPS origin of the API) should be set in production so TwiML builds a stable **`wss://`** media URL (the app can derive from `Host` / `X-Forwarded-*` if unset).
- Optional tuning: **`VOICE_MEDIA_STREAM_MAX_SEC`** (default `30`), **`VOICE_DEEPGRAM_FINAL_DEBOUNCE_MS`** (default `450`).
- **Rollback**: set `VOICE_STT_PROVIDER=twilio` or remove it, redeploy; inbound calls use Gather again.
- **Scaling**: media streams still rely on in-memory `active_calls` / `response_status`; multiple stateless workers without sticky sessions can mis-route streaming calls—prefer a single voice worker or external session affinity until Redis-backed state exists.

Ensure your jurisdiction’s consent/recording rules are satisfied; the disclosure is part of the generated greeting audio when recording is enabled.

### Linting

`npm run lint` (runs `next lint`). Requires `.eslintrc.json` in the project root (already committed with `next/core-web-vitals` preset). Pre-existing warnings exist in the codebase.

### Admin invite flow

The admin page (`/admin`) creates tenants and sends Clerk invitations. It requires:
1. **PostgreSQL** — `DATABASE_URL` in `backend/.env`.
2. **Clerk JWT verification** — `CLERK_JWKS_URL` in `backend/.env`.
3. **Admin authorization** — `ADMIN_CLERK_USER_IDS` in `backend/.env` (comma-separated Clerk user IDs).
4. **Clerk invitations** — `CLERK_SECRET_KEY` in `backend/.env`.
5. **Frontend auth** — `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` in `.env.local`.

Without `DATABASE_URL`, the admin endpoint returns 503. Without `CLERK_SECRET_KEY`, tenant creation succeeds but the invitation email is not sent.

### Client removal

When a tenant is removed via the admin page, the backend:
1. Looks up all `tenant_members` (Clerk user IDs) before deletion.
2. Deletes the tenant row (cascades to `tenant_members`).
3. Clears `tenant_id` from each member's Clerk `public_metadata`.
4. Revokes all active Clerk sessions so the user is signed out immediately.

Users are **not banned** — they can be re-invited later. The dashboard page gates all tabs behind a tenant check; removed users see a "No Access" screen.

### Backend observability (logs while testing in production)

Logs go to **stderr** with format `LEVEL|nuvatra|message`. Tune verbosity without code changes:

| Variable | Effect |
|----------|--------|
| **`LOG_LEVEL`** | `INFO` (default) or **`DEBUG`** — DEBUG shows more framework noise; pair with **`OBS_VERBOSE`** for app internals. |
| **`OBS_VERBOSE=1`** | Extra **DEBUG** lines: slot availability, booking parser context, inbound SMS thread context. Does not log full SMS bodies at INFO (lengths only where relevant). |
| **`OBS_TRACE_WEBHOOKS=1`** | **INFO** line for each **`/api/phone/*`** and **`/api/sms/*`** request: method, path, HTTP status, latency ms, **`X-Request-ID`**. Use this to match Twilio webhook delivery to your service in Render logs. |
| **`OBS_TRACE_SMS=1`** | **INFO** lines for each inbound SMS pipeline step on **`/api/sms/incoming`**: signature mode, tenant resolution, compliance keywords, staff commands, usage snapshot, session/history, OpenAI request/result (lengths and **`finish_reason`** only), outbound send result, DB persist, lead capture and **`after_inquiry`** automations. Pair with **`OBS_TRACE_WEBHOOKS`** to correlate **`request_id`**. Remove after debugging. |
| **`SETTINGS_LOAD_DEBUG=1`** | **INFO** lines for Settings dashboard loads: **`GET /api/business-info`**, **`/api/subscription`**, **`/api/sms-automations`**, **`/api/setup-status`** — response **keys** and **types** for `services` / `specials` / `reservation_rules` / `staff` (no PII). Remove after debugging. |

Front-end: **`NEXT_PUBLIC_DEBUG_SETTINGS=1`** logs which of those requests failed in the **browser console** (status / message only, no token).

Structured prefixes (grep-friendly): **`[SMS]`** (outbound/inbound, Twilio result, staff commands; detailed pipeline steps when **`OBS_TRACE_SMS`** is on), **`[VOICE]`** (incoming call, tenant resolution, GPT/booking branch), **`[SYSTEM]`** (booking created/failed, slots), **`[USAGE]`** (plan cap, webhook rate limit), **`[AUTH]`** (invalid Twilio signature, subscription blocked), **`[HTTP]`** (webhook timing when **`OBS_TRACE_WEBHOOKS`** is on). Caller/callee phones are **masked** in those lines.

After dependency updates, run **`pip install -r backend/requirements.txt`** on Render (includes **`email-validator`** for staff email validation).

### End-to-end verification

For hello-world / smoke-test validation, use the production deployments rather than only local servers:
- **Frontend**: `https://nuvatra-voice.vercel.app/`
- **Backend**: `https://nuvatra-voice.onrender.com/` (health check at `/api/health`)

### Gotchas

- The backend's `main.py` hard-crashes at import time if `OPENAI_API_KEY` is unset. Always provide at least a placeholder in `backend/.env`.
- Clerk validates publishable key format strictly. An invalid format key (e.g., `pk_test_placeholder`) causes 500 errors on every page. Either use real keys or remove them entirely for keyless mode.
- Sign-up options (email/password and OAuth) depend on **Clerk Dashboard** settings. The marketing site links to **`/sign-up`** and **`/sign-in`**. If invite-only or restricted sign-up is enabled in Clerk, behavior follows those rules.
- The frontend dev server may fail to bind port 3000 after restarts due to zombie node processes. Use port 3001 as fallback: `npx next dev --hostname 0.0.0.0 --port 3001 --turbo`.
- Backend pip packages install to `~/.local/` (user install). This is on the Python import path but scripts go to `~/.local/bin/` which may not be on `$PATH`.
- Render uses Python 3.13; `psycopg2-binary` must be `>=2.9.10` for compatibility (older versions fail with `undefined symbol: _PyInterpreterState_Get`).
- Invite `redirect_url` must point to a public route (`/`), not a protected route like `/dashboard`. The Clerk middleware blocks unauthenticated users before the SDK can process the invite ticket.
- `FRONTEND_URL` on the backend must match the production domain (e.g., `https://nuvatra-voice.vercel.app`) so Clerk invite links redirect correctly.
