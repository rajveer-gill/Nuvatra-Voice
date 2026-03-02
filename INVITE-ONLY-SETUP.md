# Invite-Only Client Onboarding Setup

This guide explains how to configure Nuvatra Voice for invite-only access: only clients you add (from cold-caller leads) can sign up and access the dashboard.

## 1. Clerk: Disable Public Sign-Up

1. Go to [Clerk Dashboard](https://dashboard.clerk.com) → your application
2. **Configure** → **Restrictions**
3. Enable **Allowlist** or **Restrict sign-ups** so that only invited users can create accounts
4. Alternatively: **User & Authentication** → **Email, Phone, Username** → disable public sign-up and use **Invitations** only

## 2. Backend Environment Variables

Set these on your backend (e.g. Render):

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (for tenants, tenant_members, etc.) |
| `CLERK_JWKS_URL` | Yes (multi-tenant) | Clerk JWKS URL for JWT verification. In Clerk Dashboard: **Configure** → **API Keys** → Backend API URL. JWKS is `https://<your-clerk-domain>/.well-known/jwks.json` |
| `CLERK_SECRET_KEY` | Yes (admin) | Clerk secret key for creating invitations |
| `ADMIN_CLERK_USER_IDS` | Yes (admin) | Comma-separated Clerk user IDs (e.g. `user_2abc123,user_2xyz789`) who can access `/admin` |
| `FRONTEND_URL` | Optional | Frontend URL for Clerk invite redirect and CORS (e.g. `https://nuvatrasite.netlify.app`). Backend already allows `nuvatrasite.netlify.app` and `nuvatrahq.com`. |
| `CLIENT_ID` | Optional | Used only in single-tenant mode (when `CLERK_JWKS_URL` is not set) |

For **single-tenant** (one deployment per client): do not set `CLERK_JWKS_URL`; set `CLIENT_ID` instead. Existing behavior is unchanged.

**Production:** For the live site (e.g. nuvatrasite.netlify.app), use Clerk **production** keys in Netlify env vars to avoid development limits and warnings.

For **multi-tenant**: set `CLERK_JWKS_URL`, `CLERK_SECRET_KEY`, and `ADMIN_CLERK_USER_IDS`.

## 3. Finding Your Clerk User ID (for Admin)

1. Sign in to your app
2. In Clerk Dashboard: **Users** → select your user → copy the **User ID** (e.g. `user_2abc123...`)
3. Add it to `ADMIN_CLERK_USER_IDS` on the backend

## 4. Admin Flow: Add a Client

1. Go to **/admin** (protected; only admins)
2. Fill in: **Client ID** (slug), **Business name**, **Twilio phone number**, **Email**
3. Click **Create tenant and send invite**
4. The system will:
   - Create a tenant in the database
   - Copy the template config to `clients/<client_id>/config.json`
   - Send a Clerk invitation to the email with `tenant_id` in metadata
5. **You must**:
   - Buy a Twilio number in Twilio Console (if not done)
   - Point the number’s webhook to `https://your-backend.onrender.com/api/phone/incoming`
   - Edit `clients/<client_id>/config.json` with business details (hours, services, etc.)

## 5. Client Flow: Accept Invite and Use Dashboard

1. Client receives Clerk invite email
2. Clicks the link, completes sign-up
3. Lands on dashboard (redirected per invite)
4. Their JWT contains `public_metadata.tenant_id`, so the backend scopes all data to their tenant

## 6. Twilio: One Number Per Client

- Each client has a Twilio number in the `tenants` table
- Point all numbers to the same webhook: `https://your-backend.onrender.com/api/phone/incoming`
- The backend looks up the tenant by the `To` number and uses that tenant’s config

### How phone-to-site works

When you add a new client with their Twilio number (via **/admin**), that number is linked to their account in the database. Every incoming call to that number is mapped to that tenant's `client_id`. All reservations (and messages, call log) made from that number are stored under that client, so they appear only in that client's dashboard. No extra implementation is required—once the number's voice webhook points to your backend, the system routes calls and data to the correct client automatically.

## 7. Checklist

- [ ] Clerk: Disable public sign-up / enable invite-only
- [ ] Backend: Set `CLERK_JWKS_URL`, `CLERK_SECRET_KEY`, `ADMIN_CLERK_USER_IDS`
- [ ] Backend: Set `DATABASE_URL` (PostgreSQL)
- [ ] Add your Clerk user ID to `ADMIN_CLERK_USER_IDS`
- [ ] Create first tenant via `/admin`
- [ ] Buy Twilio number, configure webhook, add to tenant
- [ ] Edit `clients/<client_id>/config.json` for the business
- [ ] Client accepts invite and uses dashboard
