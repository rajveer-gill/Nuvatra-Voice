# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Nuvatra Voice is an AI voice receptionist SaaS with two services:
- **Frontend**: Next.js 14 (TypeScript/React/Tailwind) — deployed on Netlify at `nuvatrasite.netlify.app`
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
| Frontend | Netlify (`nuvatrasite.netlify.app`) | Netlify dashboard > Environment variables |
| Backend | Render (`nuvatra-voice.onrender.com`) | Render dashboard > Environment tab |
| Database | Render PostgreSQL (Virginia region) | Auto-linked via `DATABASE_URL` on Render |

Key env vars for production backend (Render): `OPENAI_API_KEY`, `DATABASE_URL`, `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `ADMIN_CLERK_USER_IDS`, `FRONTEND_URL`.

Key env vars for production frontend (Netlify): `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_API_URL`.

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

### Gotchas

- The backend's `main.py` hard-crashes at import time if `OPENAI_API_KEY` is unset. Always provide at least a placeholder in `backend/.env`.
- Clerk validates publishable key format strictly. An invalid format key (e.g., `pk_test_placeholder`) causes 500 errors on every page. Either use real keys or remove them entirely for keyless mode.
- The Clerk instance is configured for **invite-only** sign-up. There is no public "Sign up" option. Autonomous agents cannot create accounts — a human must log in via the Desktop pane with an existing Clerk account to test authenticated flows (dashboard, admin).
- The frontend dev server may fail to bind port 3000 after restarts due to zombie node processes. Use port 3001 as fallback: `npx next dev --hostname 0.0.0.0 --port 3001 --turbo`.
- Backend pip packages install to `~/.local/` (user install). This is on the Python import path but scripts go to `~/.local/bin/` which may not be on `$PATH`.
- Render uses Python 3.13; `psycopg2-binary` must be `>=2.9.10` for compatibility (older versions fail with `undefined symbol: _PyInterpreterState_Get`).
- Invite `redirect_url` must point to a public route (`/`), not a protected route like `/dashboard`. The Clerk middleware blocks unauthenticated users before the SDK can process the invite ticket.
- `FRONTEND_URL` on the backend must match the production domain (e.g., `https://nuvatrasite.netlify.app`) so Clerk invite links redirect correctly.
