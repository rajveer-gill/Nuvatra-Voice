# Staging / preview environment

A place to test changes against a **real tenant + real login** without touching
production (where the live client's phone line runs). This is the gap that made
verifying the auto-body vertical awkward: localhost has no tenants, and the only
real environment is production.

You do **not** need a full prod mirror. The goal is a cheap, disposable env you
can break freely. Two pieces are already in the repo:

- **`render.yaml`** has a `previews:` block (set to `manual`).
- **`netlify.toml`** has `[context.staging]` + `[context.deploy-preview]` blocks
  that point the frontend at the staging backend + a Clerk **dev** instance.
- **`backend/scripts/seed_test_tenants.py`** creates disposable test tenants
  (one salon, one auto body), billing-exempt so they never expire.

The rest is dashboard wiring (~30 min, one time). Pick **one** option below.

---

## Prerequisites (both options)

These keep staging from touching anything real:

1. **Clerk — add a Development instance.** Clerk dashboard → your app → there's a
   built-in *Development* instance. Copy its **Publishable key** (`pk_test_…`),
   **Secret key** (`sk_test_…`), and **JWKS URL** (`https://…clerk.accounts.dev/.well-known/jwks.json`).
   Staging uses these so logins are separate from production users.
2. **Stripe — use Test mode.** Copy your `sk_test_…` key and the **test** price
   IDs. Staging never charges a real card.
3. **Twilio — optional.** Staging doesn't need a real number for dashboard/GUI
   testing. Leave `TWILIO_PHONE_NUMBER` unset; only add a test number if you want
   to place real calls.

---

## Option A — Render Preview Environments (recommended)

Ephemeral: Render spins up a throwaway backend **+ its own throwaway Postgres**
for a pull request. Best for "test this branch before I merge it."

1. **Enable previews.** `render.yaml` already has `previews: generation: manual`.
   Either keep `manual` (create previews on demand) or change to `automatic` (one
   per PR — costs a bit more). Commit + let Render pick up the blueprint.
2. **Set preview secrets.** Render dashboard → Blueprint → Preview environment
   defaults. For every `sync: false` key, give the **non-production** value:
   - `CLERK_JWKS_URL`, `CLERK_ISSUER`, `CLERK_AUDIENCE`, `CLERK_SECRET_KEY` → Clerk **dev** values
   - `STRIPE_SECRET_KEY`, `STRIPE_*_PRICE_ID`, `STRIPE_WEBHOOK_SECRET` → Stripe **test** values
   - `OPENAI_API_KEY` → a key with quota (can be the same one)
   - `PUBLIC_BASE_URL` / `FRONTEND_URL` → the preview URLs Render/Netlify generate
3. **Open a PR** (or trigger a preview manually). Render builds it and gives you a
   preview backend URL.
4. **Seed it.** From the Render preview service shell (or locally with
   `DATABASE_URL` pointed at the preview DB):
   ```
   cd backend && python scripts/seed_test_tenants.py --i-understand-this-writes-data --clerk-user <your_clerk_dev_user_id>
   ```
5. **Point the frontend at it.** A Netlify deploy-preview for the same PR uses the
   `[context.deploy-preview]` env in `netlify.toml` — set the placeholder
   `NEXT_PUBLIC_API_URL` to the preview backend URL (and the Clerk dev pk).

When the PR closes, Render tears the whole thing down. Nothing to clean up.

---

## Option B — Persistent staging (stable URL)

A long-lived `staging` you can always hit. Simpler mental model; slightly more
standing cost (one small DB + service always on).

1. **Create a `staging` git branch:** `git switch -c staging && git push -u origin staging`.
2. **Render:** create a second web service + a small Postgres from this repo, set
   its deploy branch to `staging`. Name them e.g. `nuvatra-voice-backend-staging`
   / `nuvatra-voice-db-staging`. Set all `sync: false` env vars to the **dev/test**
   values from Prerequisites. (You can skip Redis and set `VOICE_STATE_BACKEND=memory`
   to cut cost.)
3. **Netlify:** enable branch deploys for `staging`. The `[context.staging]` block
   in `netlify.toml` already points it at the staging backend + Clerk dev — just
   replace the placeholder URL/key with your real staging values.
4. **Seed once** (re-run anytime to reset):
   ```
   cd backend && python scripts/seed_test_tenants.py --i-understand-this-writes-data --clerk-user <your_clerk_dev_user_id>
   ```
5. **Workflow:** merge feature branches into `staging` to test live, then into the
   production branch to ship.

---

## Finding your Clerk dev user id

Sign in to the staging/preview frontend once with the Clerk **dev** instance, then
Clerk dashboard (Development) → Users → your user → copy the id starting with
`user_`. Pass it to `--clerk-user` so the seeded tenants are linked to you and show
up when you log in.

---

## Test loop: the auto-body vertical

Once staging is up and seeded:

1. Log in to the staging frontend → you land on **Seed Test Auto Body**.
2. **Settings → Industry** → confirm it's a **dropdown** showing "Auto body shop &
   collision center". Switch it to salon and back → you should see "Industry
   updated" each time (this exercises `POST /api/business/vertical`).
3. Confirm `GET /api/verticals` from the staging backend lists both industries.
4. (Optional) Add a Twilio test number to staging and place a call to the auto-body
   tenant — the receptionist should say "technician", not "stylist".

To reset everything to a clean state, just re-run the seed script.

---

## Safety notes

- The seed script **refuses to run** against a DB that has non-seed tenants (it
  treats that as production) unless you pass `--force`. Keep that guard.
- Seed tenant `client_id`s are prefixed `seed-test-` so they're easy to spot and
  purge.
- Never put production Clerk/Stripe/Twilio secrets on a preview or staging env.
