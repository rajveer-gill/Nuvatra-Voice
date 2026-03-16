# 24/7 Deployment Guide

This guide will help you deploy your Nuvatra Voice receptionist to run 24/7 in the cloud.

## Recommended Hosting Options

### Option 1: Railway (Recommended - Easiest) ⭐
- **Free tier**: $5/month credit (usually enough for small apps)
- **Pros**: Super easy setup, automatic deployments from GitHub, built-in environment variables
- **Cons**: Free tier limited, but very affordable paid plans
- **Best for**: Quick deployment, automatic scaling

### Option 2: Render
- **Free tier**: Available (with limitations)
- **Pros**: Simple setup, good free tier, automatic SSL
- **Cons**: Free tier spins down after inactivity (not ideal for 24/7)
- **Best for**: Testing, but upgrade to paid for 24/7

### Option 3: Fly.io
- **Free tier**: Generous free tier
- **Pros**: Great free tier, global edge network, good performance
- **Cons**: Slightly more complex setup
- **Best for**: Global performance, cost-effective

### Option 4: DigitalOcean App Platform
- **Pricing**: Starts at $5/month
- **Pros**: Reliable, good performance, easy scaling
- **Cons**: No free tier
- **Best for**: Production-ready deployment

## Quick Deploy: Railway (Recommended)

### Step 1: Create Railway Account
1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub
3. Click "New Project"

### Step 2: Deploy Backend
1. Click "Deploy from GitHub repo"
2. Select your `Nuvatra-Voice` repository
3. Railway will auto-detect it's a Python app
4. Set the **Root Directory** to: `backend`
5. Set the **Start Command** to: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Step 3: Configure Environment Variables
In Railway dashboard, go to **Variables** tab and add:
```
OPENAI_API_KEY=your_openai_api_key
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_PHONE_NUMBER=+19254815386
NGROK_URL=https://your-railway-url.railway.app
```

### Step 4: Get Your Public URL
1. Railway will give you a URL like: `https://your-app.railway.app`
2. Copy this URL - you'll need it for Twilio webhooks

### Step 5: Update Twilio Webhooks
1. Go to [Twilio Console](https://console.twilio.com)
2. Phone Numbers → Manage → Active Numbers → Your Number
3. Update webhooks to use your Railway URL:
   - **A CALL COMES IN**: `https://your-app.railway.app/api/phone/incoming`
   - **CALL STATUS CHANGES**: `https://your-app.railway.app/api/phone/status`
4. Set both to **POST** method
5. Click **Save**

### Step 6: Update NGROK_URL Environment Variable
In Railway, update the `NGROK_URL` variable to your Railway URL (no need for ngrok anymore!)

## Alternative: Render Deployment

### Step 1: Create Render Account
1. Go to [render.com](https://render.com)
2. Sign up with GitHub

### Step 2: Create New Web Service
1. Click "New" → "Web Service"
2. Connect your GitHub repository
3. Settings:
   - **Name**: `nuvatra-voice-backend`
   - **Root Directory**: `backend`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Step 3: Add PostgreSQL (production)
1. In Render dashboard, click **New** → **PostgreSQL**
2. Create a database (e.g. `nuvatra-voice-db`)
3. After creation, go to the database → **Connect** → copy the **Internal Database URL**
4. Add it as an environment variable for your web service: `DATABASE_URL` = (paste the URL)

Without `DATABASE_URL`, data is stored in memory/JSON and is lost on restart. With PostgreSQL, appointments, messages, call logs, caller memory, and booked slots persist.

### Step 4: Add Environment Variables
In Render dashboard → your web service → Environment:
```
DATABASE_URL=postgres://...   (from Step 3)
OPENAI_API_KEY=your_key
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=+19254815386
NGROK_URL=https://your-app.onrender.com
CLIENT_ID=demo-store
```

### Step 5: Deploy
1. Click "Create Web Service"
2. Wait for deployment (5-10 minutes)
3. Get your URL: `https://your-app.onrender.com`

**Note**: Free tier spins down after 15 min inactivity. Upgrade to paid ($7/month) for 24/7.

## Frontend Deployment (Production)

The Next.js app (marketing + login + dashboard) should be deployed where it runs in production (e.g. **Vercel** or **Netlify**). Set **Environment Variables** on that host — the app reads them at build/runtime.

1. Go to [vercel.com](https://vercel.com) (or Netlify), import your GitHub repo, and create a project for the Nuvatra-Voice repo.
2. In the project’s **Settings → Environment Variables**, add:

| Variable | Value |
|----------|--------|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Your Clerk publishable key (pk_test_… or pk_live_…) |
| `CLERK_SECRET_KEY` | Your Clerk secret key (sk_test_… or sk_live_…) |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL` | `/dashboard` |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL` | `/dashboard` |
| `NEXT_PUBLIC_API_URL` | Your backend URL (e.g. `https://nuvatra-voice.onrender.com`) |

3. Deploy. Sign-in and the protected dashboard will work in production only when these are set.

## Post-Deployment Checklist

- [ ] Backend deployed and running
- [ ] Environment variables configured
- [ ] Public URL obtained
- [ ] Twilio webhooks updated with new URL
- [ ] Test phone call works
- [ ] No more ngrok needed! 🎉

## Monitoring

- **Railway**: Built-in logs and metrics
- **Render**: Logs available in dashboard
- **Fly.io**: `fly logs` command

## Cost Estimates

- **Railway**: ~$5-10/month (after free credit)
- **Render**: $7/month (paid plan for 24/7)
- **Fly.io**: Free tier usually sufficient
- **DigitalOcean**: $5/month minimum

## Troubleshooting

### Server not responding
- Check environment variables are set correctly
- Verify the PORT environment variable (Railway/Render set this automatically)
- Check logs in hosting dashboard

### Twilio webhook errors
- Verify webhook URLs are correct
- Make sure URLs use HTTPS (not HTTP)
- Check backend logs for incoming requests

### Environment variables not loading
- Make sure variables are set in hosting dashboard
- Restart the service after adding variables
- Check variable names match exactly (case-sensitive)

## Common deployment issues

- **Railway "Application Error"**: Check logs (Railway → Logs). Often missing env vars or wrong **Root Directory** (set to `backend`) or **Start Command** (`uvicorn main:app --host 0.0.0.0 --port $PORT`).
- **Finding your Railway URL**: Railway dashboard → your service → **Settings** → **Domains** (or **Generate Domain**). Use this URL in Twilio webhooks and set `NGROK_URL` to it.
- **Stale build / old code**: In Railway, trigger a **Redeploy** or clear build cache in settings and redeploy.
- **Wrong Python version**: Set Python version in `backend/requirements.txt` (e.g. `python_requires>=3.11`) or use a `.python-version` or runtime file if your platform supports it.

## Environment variables reference

Use this as a single reference for every env var used by the app.

### Backend

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes (production) | PostgreSQL connection string. When set, tenants, appointments, call_log, audit_events, etc. persist. |
| `OPENAI_API_KEY` | Yes | OpenAI API key for chat and TTS. |
| `CLERK_JWKS_URL` | Yes (multi-tenant) | Clerk JWKS URL (e.g. `https://<clerk-domain>/.well-known/jwks.json`) for JWT verification. |
| `CLERK_SECRET_KEY` | Yes (admin) | Clerk secret key for creating invitations. |
| `ADMIN_CLERK_USER_IDS` | Yes (admin) | Comma-separated Clerk user IDs who can access `/admin`. |
| `FRONTEND_URL` | Recommended | Frontend URL for CORS and Stripe redirects (e.g. `https://nuvatra-voice.vercel.app`). |
| `TWILIO_ACCOUNT_SID` | Yes (phone/SMS) | Twilio account SID. |
| `TWILIO_AUTH_TOKEN` | Recommended | Twilio auth token. When set, webhook signature is validated on `/api/phone/incoming` and `/api/sms/incoming`. |
| `TWILIO_PHONE_NUMBER` | Optional | Default From number for SMS when not using per-tenant number. |
| `STRIPE_SECRET_KEY` | Yes (billing) | Stripe secret key for checkout and portal. |
| `STRIPE_WEBHOOK_SECRET` | Yes (billing) | Stripe webhook signing secret for `/api/stripe-webhook`. |
| `STRIPE_STARTER_PRICE_ID` | Yes (billing) | Stripe price ID for Starter plan (monthly). |
| `STRIPE_GROWTH_PRICE_ID` | Yes (billing) | Stripe price ID for Growth plan (monthly). |
| `STRIPE_PRO_PRICE_ID` | Yes (billing) | Stripe price ID for Pro plan (monthly). |
| `NGROK_URL` | Yes (phone) | Public backend URL (e.g. `https://your-app.onrender.com`) for TwiML callback URLs. |
| `CLIENT_ID` | Optional | Single-tenant mode: use when `CLERK_JWKS_URL` is not set. |
| `DEBUG_CORS` | Optional | Set to `1` to enable CORS debug middleware (file + console). Leave unset in production. |
| `LOG_LEVEL` | Optional | Logging level: DEBUG, INFO, WARNING, ERROR. Default: INFO. |
| `CRON_SECRET` | Yes (cron) | Shared secret for cron endpoints (`X-Cron-Secret` header). Required for appointment reminders and overage billing. |
| `REMINDER_TIMEZONE` | Optional | Timezone for "tomorrow" in reminders (e.g. `America/New_York`). Default: UTC. |
| `OVERAGE_PRICE_PER_MINUTE` | Yes (overage) | Price per minute in dollars (e.g. 0.05) for extra minutes billing. |

### Cron Jobs (Render)

To enable day-before appointment reminders (Growth/Pro plans):

1. In Render dashboard, add a **Cron Job** service.
2. **Command**: `curl -s -X POST -H "X-Cron-Secret: $CRON_SECRET" https://your-backend.onrender.com/api/cron/appointment-reminders`
3. **Schedule**: Daily at 14:00 UTC (or adjust for your timezone via `REMINDER_TIMEZONE`).
4. Add `CRON_SECRET` as an environment variable (same value as on your web service).

**Overage billing (extra minutes):**

1. Add another Cron Job service.
2. **Command**: `curl -s -X POST -H "X-Cron-Secret: $CRON_SECRET" https://your-backend.onrender.com/api/cron/process-overage`
3. **Schedule**: Monthly on the 1st (e.g. `0 15 1 * *` for 15:00 UTC on the 1st).
4. Set `OVERAGE_PRICE_PER_MINUTE` (e.g. `0.05`) and `CRON_SECRET`.

### Frontend

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Yes | Clerk publishable key. |
| `CLERK_SECRET_KEY` | Yes | Clerk secret key. |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL` | Optional | Redirect after sign-in (e.g. `/dashboard`). |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL` | Optional | Redirect after sign-up (e.g. `/dashboard`). |
| `NEXT_PUBLIC_API_URL` | Yes | Backend API base URL. |

## Audit log and retention

Audit events (admin actions, Stripe events, auth failures, business-info updates, appointment accept/reject) are stored in the **`audit_events`** table in PostgreSQL. Each row includes: `occurred_at`, `actor_type`, `actor_id`, `action`, `resource_type`, `resource_id`, `client_id`, `details` (JSONB), `ip`, `request_id`. No full PII (e.g. no message bodies) is logged.

For legal and billing protection, consider a **retention policy** (e.g. keep audit rows for 1 year) and document it in your terms or internal runbook. You can run periodic deletes (e.g. `DELETE FROM audit_events WHERE occurred_at < NOW() - INTERVAL '1 year'`) or use a scheduled job.

## Need Help?

- Railway Docs: https://docs.railway.app
- Render Docs: https://render.com/docs
- Fly.io Docs: https://fly.io/docs






