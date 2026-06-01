# Clerk JWT template setup (Option A — production auth)

The backend validates Clerk JWTs with strict **`iss`** and **`aud`** checks (`backend/auth.py`). Default Clerk session tokens do **not** include a custom `aud` claim, so production uses a **JWT template** and the frontend requests tokens with `getToken({ template: '…' })`.

## Values (Call-Surge production)

| Setting | Value |
|---------|--------|
| Clerk issuer (`CLERK_ISSUER`) | `https://clerk.call-surge.com` |
| JWKS (`CLERK_JWKS_URL`) | `https://clerk.call-surge.com/.well-known/jwks.json` |
| JWT template name | `nuvatra-backend` |
| Audience (`CLERK_AUDIENCE`) | `https://nuvatra-voice.onrender.com` |
| Frontend env | `NEXT_PUBLIC_CLERK_JWT_TEMPLATE=nuvatra-backend` |

Use the same audience string in the template claims and in Render `CLERK_AUDIENCE` (no trailing slash).

---

## 1. Create JWT template (Clerk Dashboard)

1. Open [Clerk Dashboard](https://dashboard.clerk.com) → your **production** instance.
2. Go to **Configure** → **JWT templates** → **New template**.
3. **Name:** `nuvatra-backend` (must match `NEXT_PUBLIC_CLERK_JWT_TEMPLATE`).
4. **Claims** (JSON editor):

```json
{
  "aud": "https://nuvatra-voice.onrender.com",
  "public_metadata": "{{user.public_metadata}}"
}
```

`public_metadata` is required so the backend can read `tenant_id` from the token (multi-tenant scoping).

5. Save. On the template page, confirm **Issuer** is `https://clerk.call-surge.com` (matches `CLERK_ISSUER`).

---

## 2. Backend (Render)

Set or confirm:

| Variable | Value |
|----------|--------|
| `CLERK_JWKS_URL` | `https://clerk.call-surge.com/.well-known/jwks.json` |
| `CLERK_ISSUER` | `https://clerk.call-surge.com` |
| `CLERK_AUDIENCE` | `https://nuvatra-voice.onrender.com` |

Do **not** set `ALLOW_INSECURE_WEBHOOKS` in production.

Redeploy the web service after saving env vars.

---

## 3. Frontend (Vercel)

Add:

| Variable | Value |
|----------|--------|
| `NEXT_PUBLIC_CLERK_JWT_TEMPLATE` | `nuvatra-backend` |

Redeploy production (env change alone does not update already-built client bundles until redeploy).

---

## 4. Local dev

In `backend/.env`:

```env
CLERK_JWKS_URL=https://<your-clerk-domain>/.well-known/jwks.json
CLERK_ISSUER=https://<your-clerk-domain>
CLERK_AUDIENCE=https://nuvatra-voice.onrender.com
```

Create the same JWT template name in your **Clerk test/dev** instance (audience can match production API URL or a dev-specific string — if dev-only, set `CLERK_AUDIENCE` to the same string as the template `aud` claim).

In `.env.local`:

```env
NEXT_PUBLIC_CLERK_JWT_TEMPLATE=nuvatra-backend
```

---

## 5. Verify

1. Sign in at `https://www.call-surge.com` → open **Dashboard** / **Settings**.
2. API calls should return **200**, not **401** or **500** “Clerk token validation not fully configured”.
3. Optional: dashboard **Access debug** — JWT tenant metadata should appear when present on the user.

After auth works, run the checklist in [`post-deploy-verification.md`](./post-deploy-verification.md).

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| 500 “Clerk token validation not fully configured” | Missing `CLERK_ISSUER` or `CLERK_AUDIENCE` on Render |
| 401 “Invalid token” | Template not used (`NEXT_PUBLIC_CLERK_JWT_TEMPLATE` unset or wrong name), or `aud` / `iss` mismatch |
| Dashboard loads but tenant missing | Template missing `public_metadata` claim; backend falls back to DB/Clerk API |
| Works locally, fails in prod | Vercel redeploy needed after adding `NEXT_PUBLIC_CLERK_JWT_TEMPLATE` |
