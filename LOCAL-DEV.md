# Local development (Windows)

Run the **same app** as production on your machine so you can test UI and API changes without pushing to Render/Vercel.

## What runs locally

| Service | URL | Command |
|---------|-----|---------|
| Frontend (Next.js) | http://localhost:3000 | `npm run dev:frontend` |
| Backend (FastAPI) | http://localhost:8000 | `npm run dev:backend` |
| Both | both URLs | `npm run dev` or `bin\dev.cmd` |

The frontend talks to the backend via `NEXT_PUBLIC_API_URL` in `.env.local` (must be `http://localhost:8000`).

---

## One-time setup

### 1. Prerequisites

- **Node.js 18+** (`node -v`)
- **Python 3.9+** (`python --version`) — you have Python on PATH as `python` on Windows
- **Git** (already have the repo)

Optional for full parity with production data:

- **Docker Desktop** — easiest way to run PostgreSQL locally
- **ngrok** (or similar) — only if you want **real phone calls** hitting your laptop

### 2. Install dependencies

```powershell
cd C:\Users\rajsg\OneDrive\Desktop\Nuvatra-Voice
npm install
pip install -r backend\requirements.txt
```

Or run the helper:

```powershell
npm run setup:dev
```

### 3. Frontend env (`.env.local`)

Copy the example if you do not have `.env.local` yet:

```powershell
Copy-Item .env.local.example .env.local
```

Edit `.env.local` — **minimum for local UI**:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL=/dashboard
NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL=/dashboard
```

Use the **same Clerk application** as production (test keys are fine). Without Clerk keys, sign-in and `/dashboard` will not work.

### 4. Backend env (`backend/.env`)

Copy the template:

```powershell
Copy-Item backend\.env.example backend\.env
```

You already need at least:

```env
OPENAI_API_KEY=sk-...
```

For a **production-like** dashboard (your tenant, appointments, settings in Postgres), also set:

```env
DATABASE_URL=postgresql://...
CLERK_JWKS_URL=https://<your-clerk-domain>/.well-known/jwks.json
CLERK_SECRET_KEY=sk_test_...
ADMIN_CLERK_USER_IDS=user_...
FRONTEND_URL=http://localhost:3000
```

**Where to get values**

| Variable | Source |
|----------|--------|
| `CLERK_JWKS_URL` / `CLERK_SECRET_KEY` | Clerk Dashboard → API Keys (same app as Vercel) |
| `ADMIN_CLERK_USER_IDS` | Clerk → Users → your user → User ID (same as Render) |
| `DATABASE_URL` | See options below |

#### Database options

**Option A — Local Postgres (clean tests, safe wipes)**

```powershell
docker compose up -d
```

Your `backend/.env` is already set up for this URL by default:

```env
DATABASE_URL=postgresql://nuvatra:nuvatra_dev@localhost:5433/nuvatra
```

To use Render’s database instead, replace that line with the value from Render → Environment.

Restart the backend. Tables are created on startup. Create a client via http://localhost:3000/admin (admin user required) or sign in with an invited account.

**Option B — Point at Render Postgres (fastest, uses live data)**

Copy `DATABASE_URL` from Render → your API service → Environment. Paste into `backend/.env`.

Warning: you are using **production data**. Deletes and settings changes affect the live database. Good for debugging; bad for destructive experiments.

**Option C — File-only mode (no database)**

Leave `DATABASE_URL` unset and **do not** set `CLERK_JWKS_URL`. Set:

```env
CLIENT_ID=demo-store
```

Config loads from `clients/demo-store/config.json`. The signed-in Clerk user is **not** tied to a tenant in the DB — useful for quick prompt/voice experiments only, not full dashboard testing.

---

## Daily workflow

```powershell
# From repo root
npm run dev
```

Open http://localhost:3000 → sign in → Dashboard / Settings / Appointments.

Check backend health: http://localhost:8000/api/health

Validate env before starting:

```powershell
npm run dev:check
```

### Run servers separately

```powershell
# Terminal 1
npm run dev:backend

# Terminal 2
npm run dev:frontend
```

### Clear test appointments / caller memory (local DB)

With `DATABASE_URL` set to **local** Postgres:

```sql
DELETE FROM booked_slots WHERE client_id = 'your-client-id';
DELETE FROM appointments WHERE client_id = 'your-client-id';
DELETE FROM caller_memory WHERE client_id = 'your-client-id';
```

Restart the backend after wiping so slot caches refresh.

File mode (`CLIENT_ID` only): delete `clients/<client-id>/booked_slots.json` and `caller_memory.json`, then restart the backend.

---

## Phone calls on localhost (optional)

Production Twilio webhooks need a **public HTTPS** URL. For local voice testing:

1. Start backend: `npm run dev:backend`
2. Start ngrok: `ngrok http 8000` (or `scripts\start-ngrok.bat` if configured)
3. In `backend/.env` set `NGROK_URL` and `PUBLIC_BASE_URL` to the ngrok HTTPS origin (no trailing slash)
4. Point your Twilio number’s Voice URL to `https://<ngrok>/api/phone/incoming`

See [PHONE-SETUP.md](./PHONE-SETUP.md) for details.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Port 8000 in use | `Get-NetTCPConnection -LocalPort 8000 \| ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }` |
| Port 3000 in use | Use `npx next dev --port 3001` and open http://localhost:3001 |
| Dashboard 401/403 | Set `CLERK_JWKS_URL` + `CLERK_SECRET_KEY` in `backend/.env`; sign in again |
| “No tenant assigned” | Use production DB with your user linked, or create tenant via `/admin` on local DB |
| Settings save but calls use old config | Confirm `NEXT_PUBLIC_API_URL=http://localhost:8000` and restart both servers |
| `USE_DB=False` in logs | Set `DATABASE_URL` in `backend/.env` and restart backend |
| Frontend stuck on “Starting…” | Delete `.next` folder and run `npm run dev:frontend` again |

---

## What you do **not** need to push for

- Settings UI, appointments UI, dashboard copy
- Backend API behavior (when `DATABASE_URL` + Clerk match prod)
- Prompt/greeting logic (test via Settings preview + optional ngrok call)

You **do** still push when you want Vercel/Render production updated — local dev only replaces the edit/test cycle.
