# Railway Environment Variables - Complete List

## For 24/7 Deployment (No Computer Needed!)

When you deploy to Railway, add these **5 required variables** in the Railway dashboard:

---

## Required Variables (Add These in Railway)

### 1. OPENAI_API_KEY
```
OPENAI_API_KEY=sk-your-actual-openai-api-key-here
```
**What it is**: Your OpenAI API key (for AI responses and voice)  
**Where to get it**: https://platform.openai.com/api-keys  
**Required**: ✅ YES

---

### 2. TWILIO_ACCOUNT_SID
```
TWILIO_ACCOUNT_SID=your_twilio_account_sid_here
```
**What it is**: Your Twilio Account SID  
**Where to get it**: https://console.twilio.com → Account → API Keys & Tokens  
**Required**: ✅ YES (for phone calls)

---

### 3. TWILIO_AUTH_TOKEN
```
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
```
**What it is**: Your Twilio Auth Token  
**Where to get it**: Same location as Account SID  
**Required**: ✅ YES (for phone calls)

---

### 4. TWILIO_PHONE_NUMBER
```
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
```
**What it is**: Your Twilio phone number  
**Format**: Must include country code (e.g., +1 for US)  
**Required**: ✅ YES (for phone calls)

---

### 5. NGROK_URL
```
NGROK_URL=https://your-railway-app-name.railway.app
```
**What it is**: Your Railway app URL (NOT ngrok - use Railway URL!)  
**When to set**: AFTER Railway gives you the URL  
**How to get it**: Railway dashboard → Your service → Settings → Domains  
**Required**: ✅ YES

**Important**: 
- Railway will give you a URL like: `https://nuvatra-voice-production.railway.app`
- Use that EXACT URL here (even though variable is named NGROK_URL)
- You'll set this AFTER first deployment

---

## Optional Variable (Only if deploying frontend)

### 6. FRONTEND_URL (Optional)
```
FRONTEND_URL=https://your-frontend.vercel.app
```
**What it is**: Your frontend URL (if you deploy the web interface)  
**Required**: ❌ NO (only if you deploy frontend to Vercel)

---

## Step-by-Step Setup

### Step 1: Deploy to Railway
1. Go to railway.app
2. Deploy from GitHub
3. Railway gives you a URL

### Step 2: Add Variables
In Railway dashboard → Your service → Variables tab, add:

1. `OPENAI_API_KEY` = your OpenAI key
2. `TWILIO_ACCOUNT_SID` = your Twilio Account SID
3. `TWILIO_AUTH_TOKEN` = your Twilio Auth Token
4. `TWILIO_PHONE_NUMBER` = +1XXXXXXXXXX
5. `NGROK_URL` = your Railway URL (from Step 1)

### Step 3: Update Twilio Webhooks
1. Go to Twilio Console
2. Phone Numbers → Your Number
3. Update webhooks to use your Railway URL:
   - A CALL COMES IN: `https://your-railway-url.railway.app/api/phone/incoming`
   - CALL STATUS: `https://your-railway-url.railway.app/api/phone/status`

### Step 4: Done!
✅ Your AI receptionist is now running 24/7!  
✅ No computer needed  
✅ Businesses can call anytime  

---

## Quick Reference

**Minimum Required (5 variables)**:
- OPENAI_API_KEY
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_PHONE_NUMBER
- NGROK_URL (your Railway URL)

**That's it!** Once these are set, your service runs 24/7 automatically.


