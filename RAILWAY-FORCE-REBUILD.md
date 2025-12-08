# Railway Force Rebuild Instructions

## Problem
Railway is using cached old code. The version marker is NOT appearing in logs, which means Railway hasn't deployed the new code.

## Solution: Manual Cache Clear

### Option 1: Via Railway Dashboard (RECOMMENDED)

1. Go to https://railway.app
2. Log in and select your project
3. Click on your service (the backend service)
4. Go to **Settings** tab
5. Scroll down to find **"Clear Build Cache"** or **"Redeploy"** button
6. Click it to force a fresh build

### Option 2: Via Deployments Tab

1. Go to Railway Dashboard → Your Service
2. Click **Deployments** tab
3. Find the latest deployment
4. Click the **"..."** menu (three dots)
5. Select **"Redeploy"** or **"Clear Cache and Redeploy"**

### Option 3: Check Root Directory Setting

1. Railway Dashboard → Your Service → Settings
2. Look for **"Root Directory"** setting
3. It should be **EMPTY** (not set to `backend`)
4. If it's set to `backend`, Railway might not be reading files correctly
5. Clear it or set it to empty

### Option 4: Create New Deployment

1. Railway Dashboard → Deployments
2. Click **"New Deployment"** or **"Redeploy"**
3. This forces a completely fresh build

## What to Check After Rebuild

After clearing cache and redeploying, check logs for:

```
============================================================
DEBUG: NEW CODE LOADED - Version 2025-12-08-07:00
============================================================
```

If you see this, Railway is running new code!
If you DON'T see this, Railway is still using cached code.


