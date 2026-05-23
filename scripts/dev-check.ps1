# Quick checks before npm run dev (Windows).
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Nuvatra Voice - dev check`n" -ForegroundColor Cyan

function Port-InUse($port) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    return [bool]$c
}

foreach ($p in @(3000, 8000)) {
    if (Port-InUse $p) {
        Write-Host "WARN  Port $p is already in use (stop old dev servers or pick another port)" -ForegroundColor Yellow
    } else {
        Write-Host "OK    Port $p is free" -ForegroundColor Green
    }
}

# Frontend
if (Test-Path ".env.local") {
    $apiLine = Get-Content ".env.local" | Where-Object { $_ -match '^\s*NEXT_PUBLIC_API_URL=' } | Select-Object -First 1
    $api = (($apiLine -split '=', 2)[1]).Trim()
    if ($api -match 'localhost|127\.0\.0\.1') {
        Write-Host "OK    NEXT_PUBLIC_API_URL points to local backend ($api)" -ForegroundColor Green
    } else {
        Write-Host "WARN  NEXT_PUBLIC_API_URL is not localhost - frontend will hit production: $api" -ForegroundColor Yellow
    }
    $pk = Get-Content ".env.local" | Where-Object { $_ -match '^\s*NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=\s*\S+' }
    if ($pk) { Write-Host "OK    Clerk publishable key set in .env.local" -ForegroundColor Green }
    else { Write-Host "WARN  NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY missing" -ForegroundColor Yellow }
} else {
    Write-Host "FAIL  .env.local missing - run: Copy-Item .env.local.example .env.local" -ForegroundColor Red
}

# Backend
if (Test-Path "backend\.env") {
    Push-Location backend
    $envReport = & python scripts/dev_env_status.py 2>&1
    Pop-Location
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARN  Could not read backend/.env ($envReport)" -ForegroundColor Yellow
    } else {
        $envReport | ForEach-Object {
            if ($_ -match '=set$') { Write-Host "OK    backend $_" -ForegroundColor Green }
            else { Write-Host "      backend $_" -ForegroundColor DarkGray }
        }
        if (($envReport | Where-Object { $_ -eq 'DATABASE_URL=set' }).Count -eq 0 -and ($envReport | Where-Object { $_ -eq 'CLIENT_ID=set' }).Count -eq 0) {
            Write-Host "WARN  No DATABASE_URL or CLIENT_ID - limited dev mode (LOCAL-DEV.md Option C)" -ForegroundColor Yellow
        }
        if (($envReport | Where-Object { $_ -eq 'CLERK_JWKS_URL=set' }).Count -eq 0) {
            Write-Host "WARN  CLERK_JWKS_URL unset - set it in backend/.env to match production" -ForegroundColor Yellow
        }
        if (($envReport | Where-Object { $_ -eq 'ADMIN_CLERK_USER_IDS=set' }).Count -eq 0) {
            Write-Host "WARN  ADMIN_CLERK_USER_IDS unset - needed for /admin" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "FAIL  backend\.env missing - run: Copy-Item backend\.env.example backend\.env" -ForegroundColor Red
}

try {
    $r = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) {
        Write-Host "OK    Backend already running at http://localhost:8000" -ForegroundColor Green
    }
} catch {
    Write-Host "      Backend not running yet (start with npm run dev)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Start: npm run dev  |  Docs: LOCAL-DEV.md" -ForegroundColor Cyan
Write-Host ""
