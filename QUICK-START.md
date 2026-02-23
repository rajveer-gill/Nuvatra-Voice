# Quick Start Guide

## Starting the Servers

### One command (backend + frontend together)

From the project root:

- **Windows (CMD):** `bin\dev.cmd`
- **Windows (PowerShell):** `.\bin\dev.cmd` or `npm run dev`
- **Mac/Linux:** `./bin/dev` or `npm run dev`

You should see both servers start (backend on port 8000, frontend on port 3000). Stop with `Ctrl+C`.

### Or start separately (two terminals)

**Terminal 1 – Backend:**

```bash
cd backend
python main.py
```

Wait for: `INFO:     Uvicorn running on http://0.0.0.0:8000`

**Terminal 2 – Frontend:**

```powershell
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











