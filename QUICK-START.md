# Quick Start Guide

## Starting the Servers

### Backend (Terminal 1)

```bash
cd backend
python main.py
```

Wait for: `INFO:     Uvicorn running on http://0.0.0.0:8000`

### Frontend (Terminal 2 - NEW WINDOW)

```powershell
# Refresh PATH if npm not recognized
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# Clear cache if stuck on "Starting..."
Remove-Item -Path .next -Recurse -Force -ErrorAction SilentlyContinue

# Start frontend
npm run dev
```

Wait for: `✓ Ready in XXXXms` and `Local: http://localhost:3000`

### Open Browser

Go to: **http://localhost:3000**

---

## Troubleshooting

### Port 8000 in use?
```powershell
Get-NetTCPConnection -LocalPort 8000 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### Frontend stuck on "Starting..."?
1. Stop (Ctrl+C)
2. Clear cache: `Remove-Item -Path .next -Recurse -Force`
3. Restart: `npm run dev`





