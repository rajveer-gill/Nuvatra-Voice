# One-time (or repeat) local dev setup for Nuvatra Voice on Windows.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Nuvatra Voice - local dev setup" -ForegroundColor Cyan
Write-Host "Repo: $Root`n"

function Test-Command($name) {
    if (Get-Command $name -ErrorAction SilentlyContinue) { return $true }
    return $false
}

$ok = $true
if (-not (Test-Command node)) { Write-Host "Missing: Node.js (https://nodejs.org)" -ForegroundColor Red; $ok = $false }
else { Write-Host "OK  node $(node -v)" -ForegroundColor Green }
if (-not (Test-Command python)) { Write-Host "Missing: Python 3 (https://www.python.org)" -ForegroundColor Red; $ok = $false }
else { Write-Host "OK  python $(python --version 2>&1)" -ForegroundColor Green }
if (-not $ok) { exit 1 }

Write-Host "`nInstalling npm packages..." -ForegroundColor Yellow
npm install
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Installing Python packages..." -ForegroundColor Yellow
pip install -r backend\requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path ".env.local")) {
    Copy-Item ".env.local.example" ".env.local"
    Write-Host "Created .env.local from .env.local.example - add Clerk keys and confirm NEXT_PUBLIC_API_URL=http://localhost:8000" -ForegroundColor Yellow
} else {
    Write-Host "OK  .env.local already exists" -ForegroundColor Green
}

if (-not (Test-Path "backend\.env")) {
    Copy-Item "backend\.env.example" "backend\.env"
    Write-Host "Created backend\.env from backend\.env.example - add OPENAI_API_KEY and (recommended) DATABASE_URL + Clerk vars" -ForegroundColor Yellow
} else {
    Write-Host "OK  backend\.env already exists" -ForegroundColor Green
}

Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Edit .env.local  - NEXT_PUBLIC_API_URL=http://localhost:8000 + Clerk keys"
Write-Host "  2. Edit backend\.env - OPENAI_API_KEY; for full dashboard copy Render/Clerk vars (see LOCAL-DEV.md)"
Write-Host "  3. Optional: docker compose up -d  then DATABASE_URL=postgresql://nuvatra:nuvatra_dev@localhost:5433/nuvatra"
Write-Host "  4. npm run dev:check"
Write-Host "  5. npm run dev"
Write-Host "`nDocs: LOCAL-DEV.md`n"
