# Troubleshooting "Application Error"

## Step 1: Check Railway Logs

1. Go to Railway dashboard
2. Click on your "Nuvatra-Voice" service
3. Click **"Logs"** tab
4. Look for **red error messages**
5. Copy the error message and share it

Common errors you might see:
- `ModuleNotFoundError` - Missing Python package
- `OPENAI_API_KEY not found` - Missing environment variable
- `Connection error` - Network issue
- `500 Internal Server Error` - Backend crash

---

## Step 2: Verify Environment Variables

In Railway → Variables tab, make sure you have:

✅ `OPENAI_API_KEY` - Your OpenAI key (starts with `sk-`)
✅ `TWILIO_ACCOUNT_SID` - Your Twilio Account SID
✅ `TWILIO_AUTH_TOKEN` - Your Twilio Auth Token
✅ `TWILIO_PHONE_NUMBER` - +19254815386
✅ `NGROK_URL` - https://nuvatra-voice-production.up.railway.app

---

## Step 3: Check Service Status

In Railway dashboard:
1. Make sure your service shows **"Active"** (green)
2. Check if there are any deployment errors
3. Make sure the latest deployment succeeded

---

## Step 4: Common Fixes

### Fix 1: Missing Dependencies
If you see `ModuleNotFoundError`:
- Railway should auto-install from `requirements.txt`
- Check if deployment completed successfully

### Fix 2: Wrong Port
Railway sets `$PORT` automatically - make sure your Procfile uses `$PORT`

### Fix 3: Environment Variables Not Loading
- Make sure variables are saved in Railway
- Redeploy after adding variables

---

## What to Share

When asking for help, share:
1. **The exact error from Railway logs**
2. **Screenshot of Railway Variables tab** (with values masked)
3. **Railway deployment status**

This will help diagnose the issue quickly!


