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

### Gotchas

- The backend's `main.py` hard-crashes at import time if `OPENAI_API_KEY` is unset. Always provide at least a placeholder in `backend/.env`.
- Clerk validates publishable key format strictly. An invalid format key (e.g., `pk_test_placeholder`) causes 500 errors on every page. Either use real keys or remove them entirely for keyless mode.
- Backend pip packages install to `~/.local/` (user install). This is on the Python import path but scripts go to `~/.local/bin/` which may not be on `$PATH`.
