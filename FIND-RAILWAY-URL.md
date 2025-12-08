# How to Find Your Railway URL

## Method 1: Settings → Domains (Easiest)

1. In Railway dashboard, click on your service: **"Nuvatra-Voice"**
2. Click on **"Settings"** tab (top navigation)
3. Scroll down to **"Domains"** section
4. You'll see your Railway URL there, like:
   ```
   https://nuvatra-voice-production.railway.app
   ```
5. Copy that URL!

---

## Method 2: Service Overview

1. In Railway dashboard, click on your service: **"Nuvatra-Voice"**
2. Look at the top of the page - your URL might be displayed there
3. Or check the **"Deployments"** tab - it might show the URL

---

## Method 3: Generate a Domain

If you don't see a domain yet:

1. Go to **Settings** → **Domains**
2. Click **"Generate Domain"** or **"Add Domain"**
3. Railway will create a URL like: `https://nuvatra-voice-production.railway.app`
4. Copy that URL!

---

## Method 4: Check Deployment Logs

1. Go to **"Deployments"** tab
2. Click on the latest deployment
3. Check the logs - the URL might be mentioned there

---

## What the URL Looks Like

Your Railway URL will be in this format:
```
https://[your-service-name]-[random-id].railway.app
```

Example:
```
https://nuvatra-voice-production.railway.app
```

---

## After You Find It

1. Copy the full URL (including `https://`)
2. Go back to **Variables** tab
3. Add `NGROK_URL` with that URL as the value
4. Click **"Add"** then **"Deploy"**

---

## Quick Checklist

- [ ] Found Railway URL in Settings → Domains
- [ ] Copied the full URL (with https://)
- [ ] Added NGROK_URL variable with that URL
- [ ] Clicked "Add" and "Deploy"


