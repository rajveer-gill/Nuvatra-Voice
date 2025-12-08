# Fix Python Version in Railway

## The Problem
Railway Railpack is using Python 3.13 by default, which causes pydantic-core build failures.

## Solution: Configure Python Version in Railway Settings

### Option 1: Railway Dashboard (Recommended)

1. Go to Railway dashboard
2. Click your service: **"Nuvatra-Voice"**
3. Click **"Settings"** tab
4. Look for **"Build"** or **"Environment"** section
5. Find **"Python Version"** or **"Runtime Version"**
6. Set it to: **Python 3.11** or **3.11.9**
7. Save and redeploy

### Option 2: Use .python-version file

Create `.python-version` file in `backend/` directory:
```
3.11.9
```

### Option 3: Use mise.toml (Railway uses mise)

Create `mise.toml` in `backend/` directory:
```toml
[tools]
python = "3.11.9"
```

### Option 4: Use Dockerfile (Most Reliable)

If Railway settings don't work, we can switch to Dockerfile deployment which gives full control.

---

## Quick Fix to Try Now

1. Railway Dashboard → Your Service → Settings
2. Look for Python/Runtime version setting
3. Change from 3.13 to 3.11
4. Redeploy

This should fix the pydantic-core build issue!


