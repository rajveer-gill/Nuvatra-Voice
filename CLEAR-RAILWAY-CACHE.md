# How to Clear Railway Build Cache

## Problem
Railway is using cached dependencies and not installing the updated `openai==1.54.5` and `httpx==0.27.0` versions.

## Solution: Manual Cache Clear

### Step 1: Go to Railway Dashboard
1. Open https://railway.app
2. Log in to your account
3. Select your project

### Step 2: Clear Build Cache
**Option A: Via Settings**
1. Click on your service (the one running the backend)
2. Go to **Settings** tab
3. Scroll down to find **"Clear Build Cache"** or **"Redeploy"** button
4. Click it to force a fresh build

**Option B: Via Deployments**
1. Click on your service
2. Go to **Deployments** tab
3. Find the latest deployment
4. Click the **"..."** menu (three dots)
5. Select **"Redeploy"** or **"Clear Cache and Redeploy"**

**Option C: Create New Deployment**
1. Go to **Deployments** tab
2. Click **"New Deployment"** or **"Redeploy"**
3. This will force a complete rebuild

### Step 3: Verify Build Logs
After redeploying, check the build logs. You should see:
```
Collecting openai==1.54.5
Collecting httpx==0.27.0
Successfully installed openai-1.54.5
Successfully installed httpx-0.27.0
```

If you see `openai-1.3.0` or any version < 1.12.0, the cache is still being used.

### Step 4: Check Runtime Logs
After the build completes, check runtime logs. You should see:
```
DEBUG: httpx version: 0.27.0
DEBUG: openai version: 1.54.5
INFO: Uvicorn running on http://0.0.0.0:8000
```

If you still see the `TypeError: Client.__init() got an unexpected keyword argument 'proxies'` error, Railway is still using cached dependencies.

## Alternative: Contact Railway Support
If manual cache clearing doesn't work, you may need to:
1. Contact Railway support
2. Or create a new service and redeploy (nuclear option)

## Why This Happens
Railway caches Docker layers and pip installations to speed up builds. Sometimes the cache doesn't invalidate properly when dependencies change, especially when using `>=` version specifiers.

By pinning exact versions (`==`) and manually clearing cache, we force Railway to do a fresh install.


