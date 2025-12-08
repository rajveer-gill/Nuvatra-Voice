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

### Step 3: Add Environment Variables
In Render dashboard → Environment:
```
OPENAI_API_KEY=your_key
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=+19254815386
NGROK_URL=https://your-app.onrender.com
```

### Step 4: Deploy
1. Click "Create Web Service"
2. Wait for deployment (5-10 minutes)
3. Get your URL: `https://your-app.onrender.com`

**Note**: Free tier spins down after 15 min inactivity. Upgrade to paid ($7/month) for 24/7.

## Frontend Deployment (Optional)

For the web interface, deploy to **Vercel** (free, perfect for Next.js):

1. Go to [vercel.com](https://vercel.com)
2. Import your GitHub repository
3. Set environment variable:
   - `NEXT_PUBLIC_API_URL`: Your backend URL (Railway/Render URL)
4. Deploy!

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

## Need Help?

- Railway Docs: https://docs.railway.app
- Render Docs: https://render.com/docs
- Fly.io Docs: https://fly.io/docs

