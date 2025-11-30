# Quick Setup Guide

## Prerequisites

- **Node.js 18+** and npm (or yarn)
- **Python 3.9+** and pip
- **OpenAI API Key** (get one at https://platform.openai.com/api-keys)

## Step-by-Step Setup

### 1. Install Frontend Dependencies

```bash
npm install
```

### 2. Install Backend Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Environment Variables

Create a `.env.local` file in the root directory:

```env
OPENAI_API_KEY=sk-your-actual-api-key-here
NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Important:** Replace `sk-your-actual-api-key-here` with your actual OpenAI API key.

### 4. Start the Backend Server

Open **Terminal 1** and run:

```bash
cd backend
python main.py
```

**Expected output:**
```
✓ API Key loaded successfully (length: 164)

==================================================
Starting Nuvatra Voice Backend Server
==================================================
Server will run on: http://0.0.0.0:8000
Local access: http://localhost:8000
==================================================

INFO:     Started server process [XXXXX]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Keep this terminal open!**

### 5. Start the Frontend

Open a **NEW terminal (Terminal 2)** and run:

**Windows PowerShell:**
```powershell
# Refresh PATH (required if npm is not recognized)
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# Clear Next.js cache if frontend gets stuck on "Starting..."
Remove-Item -Path .next -Recurse -Force -ErrorAction SilentlyContinue

# Start the frontend
npm run dev
```

**Mac/Linux or if npm is already in PATH:**
```bash
npm run dev
```

**Expected output:**
```
> nuvatra-voice@1.0.0 dev
> next dev

  ▲ Next.js 14.2.33
  - Local:        http://localhost:3000

 ✓ Starting...
 ✓ Ready in XXXXms
```

**Keep this terminal open!**

**Note:** If the frontend gets stuck on "Starting...", stop it (Ctrl+C), clear the cache with the command above, and restart.

### 6. Open in Browser

Navigate to `http://localhost:3000` in your browser.

## Testing the System

1. Click "Start Call" on the main page
2. Allow microphone access when prompted
3. Speak naturally - the AI will respond
4. Try saying:
   - "I'd like to schedule an appointment"
   - "Can I leave a message?"
   - "What are your business hours?"
   - "I need to speak with sales"

## Troubleshooting

### Port Already in Use (Backend)

If you see: `ERROR: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8000)`

**Solution:**
```powershell
# Kill the process using port 8000
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }

# Or kill all Python processes
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

Then restart the backend.

### npm Not Recognized (Frontend)

If you see: `npm : The term 'npm' is not recognized`

**Solution:**
```powershell
# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# Then run npm commands
npm run dev
```

### Frontend Stuck on "Starting..."

**Solution:**
1. Stop the process (Ctrl+C)
2. Clear the Next.js cache:
   ```powershell
   Remove-Item -Path .next -Recurse -Force -ErrorAction SilentlyContinue
   ```
3. Restart:
   ```powershell
   npm run dev
   ```

### Microphone Not Working
- Ensure your browser has microphone permissions
- Use Chrome or Edge for best Web Speech API support
- Check browser console for errors

### Backend Connection Issues
- Verify the backend is running on port 8000
- Check that `NEXT_PUBLIC_API_URL` matches your backend URL
- Ensure CORS is properly configured

### OpenAI API Errors
- Verify your API key is correct in `backend/.env`
- Check that you have credits in your OpenAI account
- Ensure the API key has proper permissions

## Browser Compatibility

The Web Speech API works best in:
- ✅ Chrome/Edge (Chromium)
- ✅ Safari (limited support)
- ❌ Firefox (not supported)

For production, consider using a more robust voice solution like:
- Twilio Voice
- Vonage Voice API
- WebRTC with a media server


