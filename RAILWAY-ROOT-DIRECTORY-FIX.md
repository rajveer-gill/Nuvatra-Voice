# Railway Root Directory Fix

## CRITICAL ISSUE
Railway is running OLD code. The version marker at the top of `backend/main.py` is NOT appearing in logs, which means Railway hasn't deployed the new code.

## Possible Causes

### 1. Root Directory Setting (MOST LIKELY)
Railway might be reading from the wrong directory.

**Check this in Railway Dashboard:**
1. Go to your service
2. Click **Settings**
3. Look for **"Root Directory"** or **"Working Directory"**
4. It should be **EMPTY** (not set to `backend`)
5. If it's set to `backend`, clear it or set it to empty

**Why this matters:**
- If Root Directory is set to `backend`, Railway might be looking for files in the wrong place
- The Procfile says `cd backend && uvicorn main:app`, so Root Directory should be empty

### 2. Build Cache
Railway is using cached Docker layers or pip cache.

**Solution:**
1. Railway Dashboard → Your Service → Settings
2. Find **"Clear Build Cache"** or **"Redeploy"**
3. Click **"Clear Cache and Redeploy"** (not just "Redeploy")

### 3. Check Build Logs
Look at the BUILD logs (not runtime logs) to see:
- What versions of openai and httpx are being installed
- Which requirements.txt file is being read

**In Railway Dashboard:**
1. Go to **Deployments** tab
2. Click on the latest deployment
3. Look at the **Build** phase logs
4. Search for: `Collecting openai` or `Successfully installed openai`

### 4. Verify Code is Deployed
The version marker should print at the very start of runtime logs:
```
============================================================
DEBUG: NEW CODE LOADED - Version 2025-12-08-07:10
DEBUG: Using openai==1.40.0 and httpx==0.27.0
============================================================
```

**If you don't see this**, Railway is running old code.

## Next Steps
1. Check Root Directory setting
2. Clear build cache and redeploy
3. Check build logs for installed versions
4. Verify version marker appears in runtime logs


