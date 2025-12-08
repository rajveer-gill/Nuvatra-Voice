# Render Deployment Guide

## Why Switch to Render?

- **Better caching behavior** - Render doesn't have the aggressive caching issues Railway has
- **Clearer build process** - More transparent about what's being installed
- **Better logs** - Easier to see what's happening during build and runtime
- **Free tier available** - Good for testing (though spins down after inactivity)

## Step-by-Step Migration

### Step 1: Create Render Account

1. Go to [render.com](https://render.com)
2. Sign up with GitHub (recommended - easier deployments)
3. Verify your email

### Step 2: Create New Web Service

1. In Render dashboard, click **"New +"** → **"Web Service"**
2. Connect your GitHub account if not already connected
3. Select your repository: `rajveer-gill/Nuvatra-Voice`
4. Click **"Connect"**

### Step 3: Configure Service Settings

Fill in these settings:

- **Name**: `nuvatra-voice-backend` (or any name you prefer)
- **Region**: Choose closest to you (e.g., `Oregon (US West)`)
- **Branch**: `main`
- **Root Directory**: `backend` ⚠️ **IMPORTANT**
- **Runtime**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Step 4: Add Environment Variables

Click **"Environment"** tab and add these variables:

```
OPENAI_API_KEY=your_openai_api_key_here
TWILIO_ACCOUNT_SID=your_twilio_account_sid_here
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
NGROK_URL=https://your-app-name.onrender.com
FRONTEND_URL=https://your-frontend-url.com (optional)
```

**Important**: 
- Don't set `NGROK_URL` yet - wait until you get your Render URL
- Render will give you a URL like: `https://nuvatra-voice-backend.onrender.com`
- After deployment, update `NGROK_URL` to match your Render URL

### Step 5: Deploy

1. Click **"Create Web Service"** at the bottom
2. Render will start building (takes 5-10 minutes)
3. Watch the build logs - you should see:
   - `Collecting openai==1.40.0`
   - `Successfully installed openai-1.40.0`
   - `Successfully installed httpx-0.27.0`
4. Once deployed, you'll get a URL like: `https://nuvatra-voice-backend.onrender.com`

### Step 6: Update Environment Variables

1. After deployment, copy your Render URL
2. Go to **Environment** tab
3. Update `NGROK_URL` to: `https://your-actual-render-url.onrender.com`
4. Click **"Save Changes"** - Render will auto-redeploy

### Step 7: Update Twilio Webhooks

1. Go to [Twilio Console](https://console.twilio.com)
2. Phone Numbers → Manage → Active Numbers → Your Number (+1 925-481-5386)
3. Update webhooks:
   - **A CALL COMES IN**: `https://your-render-url.onrender.com/api/phone/incoming`
   - **CALL STATUS CHANGES**: `https://your-render-url.onrender.com/api/phone/status`
4. Set both to **POST** method
5. Click **Save**

### Step 8: Verify Deployment

1. Check Render logs - you should see:
   ```
   ============================================================
   DEBUG: NEW CODE LOADED - Version 2025-12-08-07:10
   DEBUG: Using openai==1.40.0 and httpx==0.27.0
   ============================================================
   ```
2. Test by calling your Twilio number
3. The AI should greet you!

## Render vs Railway

| Feature | Render | Railway |
|---------|--------|---------|
| Free Tier | ✅ Yes (spins down) | ✅ Yes ($5 credit) |
| 24/7 Free | ❌ No ($7/month) | ✅ Yes (with credit) |
| Build Cache Issues | ✅ Rare | ❌ Common |
| Logs Clarity | ✅ Excellent | ⚠️ Good |
| Setup Ease | ✅ Easy | ✅ Easy |

## Pricing

- **Free Tier**: Spins down after 15 min inactivity (not ideal for phone service)
- **Starter Plan**: $7/month - Always on, perfect for 24/7 phone service
- **Professional**: $25/month - Better performance, more resources

**For your AI receptionist business, the $7/month Starter plan is recommended.**

## Troubleshooting

### Build Fails

1. Check build logs in Render dashboard
2. Look for errors like "ModuleNotFoundError"
3. Verify `Root Directory` is set to `backend`
4. Verify `requirements.txt` exists in `backend/` directory

### Server Not Starting

1. Check runtime logs
2. Look for the version marker: `DEBUG: NEW CODE LOADED`
3. Verify all environment variables are set
4. Check that `PORT` is being used (Render sets this automatically)

### Twilio Webhook Errors

1. Verify webhook URLs use HTTPS (not HTTP)
2. Check Render logs for incoming requests
3. Make sure Render URL is accessible (not spinning down)

### Package Version Issues

If you see `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`:

1. Check build logs - should show `openai-1.40.0` installing
2. If it shows `openai-1.3.0`, Render is using cached build
3. Go to **Settings** → **Clear Build Cache** → **Redeploy**

## Next Steps After Deployment

1. ✅ Test phone call works
2. ✅ Monitor logs for any errors
3. ✅ Update Twilio webhooks
4. ✅ Consider upgrading to Starter plan ($7/month) for 24/7 service
5. ✅ Set up monitoring/alerts (optional)

## Need Help?

- Render Docs: https://render.com/docs
- Render Support: https://render.com/support
- Check logs in Render dashboard for detailed error messages

