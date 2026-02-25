# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Nuvatra Voice is an AI voice receptionist SaaS with two services:
- **Frontend**: Next.js 14 (TypeScript/React/Tailwind) on port 3000
- **Backend**: Python FastAPI on port 8000

See `README.md` for standard commands (`npm run dev`, `npm run dev:frontend`, `npm run dev:backend`, `npm run lint`, `npm run build`).

### Running services

**Backend** (`cd backend && python3 main.py`):
- Requires `backend/.env` with `OPENAI_API_KEY`. Use a placeholder (`sk-placeholder-for-dev-environment`) to start the server without a real key; the pre-warm step will fail gracefully. AI conversation endpoints require a real key.
- Use `python3` not `python` (only `python3` is on PATH in this environment).
- Twilio and PostgreSQL are optional; the backend falls back to in-memory storage and disables phone features when credentials are absent.

**Frontend** (`npx next dev --hostname 0.0.0.0 --port 3000 --turbo`):
- Clerk authentication is used for `/dashboard` and `/admin` routes. Without real Clerk keys, remove `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` from `.env.local` to enable Clerk's keyless/dev mode (temporary dev keys).
- The `.env.local` must have `NEXT_PUBLIC_API_URL=http://localhost:8000` for frontend-to-backend communication.
- `next build` will fail without valid Clerk keys (static page generation requires them). Dev mode (`next dev`) works fine.

### Linting

`npm run lint` (runs `next lint`). Requires `.eslintrc.json` in the project root (already committed with `next/core-web-vitals` preset). Pre-existing warnings exist in the codebase.

### Admin invite flow

The admin page (`/admin`) creates tenants and sends Clerk invitations. It requires:
1. **PostgreSQL** — `DATABASE_URL` in `backend/.env` (e.g. `postgresql://nuvatra:nuvatra@localhost:5432/nuvatra_voice`). Start PostgreSQL with `sudo pg_ctlcluster 16 main start`.
2. **Clerk JWT verification** — `CLERK_JWKS_URL` in `backend/.env` (from Clerk Dashboard > API Keys > Advanced > JWKS URL).
3. **Admin authorization** — `ADMIN_CLERK_USER_IDS` in `backend/.env` (comma-separated Clerk user IDs).
4. **Clerk invitations** — `CLERK_SECRET_KEY` in `backend/.env` (from Clerk Dashboard).
5. **Frontend auth** — `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` in `.env.local` (the `pk_test_...` key from Clerk Dashboard).

Without `DATABASE_URL`, the admin endpoint returns 503. Without `CLERK_SECRET_KEY`, tenant creation succeeds but the invitation email is not sent.

### Gotchas

- The backend's `main.py` hard-crashes at import time if `OPENAI_API_KEY` is unset. Always provide at least a placeholder in `backend/.env`.
- Clerk validates publishable key format strictly. An invalid format key (e.g., `pk_test_placeholder`) causes 500 errors on every page. Either use real keys or remove them entirely for keyless mode.
- The Clerk instance is configured for **invite-only** sign-up. There is no public "Sign up" option. Autonomous agents cannot create accounts — a human must log in via the Desktop pane with an existing Clerk account to test authenticated flows (dashboard, admin).
- The frontend dev server may fail to bind port 3000 after restarts due to zombie node processes. Use port 3001 as fallback: `npx next dev --hostname 0.0.0.0 --port 3001 --turbo`.
- Backend pip packages install to `~/.local/` (user install). This is on the Python import path but scripts go to `~/.local/bin/` which may not be on `$PATH`.
