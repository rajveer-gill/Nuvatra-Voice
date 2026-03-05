# Nuvatra Voice - AI Voice Receptionist

An intelligent AI-powered voice receptionist for businesses: handle calls, schedule appointments, take messages, and route inquiries.

## Features

- **Voice**: Real-time speech-to-text and text-to-speech; premium AI voices (OpenAI TTS-1-HD)
- **Phone**: Answer real calls via Twilio
- **AI**: OpenAI GPT for natural conversations
- **Appointments**: Schedule and manage; accept/reject from dashboard
- **Messages**: Record and store caller messages
- **Dashboard**: Monitor calls, appointments, and analytics

## Tech Stack

- **Frontend**: Next.js 14, React, TypeScript, Tailwind CSS
- **Backend**: Python FastAPI
- **AI**: OpenAI GPT-4, TTS-1-HD
- **Phone**: Twilio

## Services We Use

| Service | Purpose |
|--------|---------|
| **Render** | Backend API and PostgreSQL (24/7 hosting) |
| **Vercel** | Frontend (marketing site + dashboard) deployment |
| **Twilio** | Phone numbers, voice webhooks, SMS (calls and texts) |
| **Clerk** | Authentication (sign-in, invite-only, JWT for API) |
| **Squarespace** | Marketing/company website (separate from this app) |

See [DEPLOYMENT.md](./DEPLOYMENT.md) for Render/Vercel setup; [PHONE-SETUP.md](./PHONE-SETUP.md) for Twilio; [AUTH-SETUP.md](./AUTH-SETUP.md) for Clerk.

## Quick Start

**Prerequisites:** Node.js 18+, Python 3.9+, OpenAI API key

1. **Install**
   ```bash
   npm install
   pip install -r backend/requirements.txt
   ```

2. **Environment**  
   Create `backend/.env` and root `.env.local`:
   ```env
   # backend/.env
   OPENAI_API_KEY=your_openai_api_key

   # .env.local (frontend)
   NEXT_PUBLIC_API_URL=http://localhost:8000
   NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_xxxxx  # from clerk.com
   CLERK_SECRET_KEY=sk_test_xxxxx                   # from clerk.com
   ```
   See **[AUTH-SETUP.md](./AUTH-SETUP.md)** for Clerk setup.

3. **Run both servers (one command)**
   - Windows: `bin\dev.cmd` or `npm run dev`
   - Mac/Linux: `./bin/dev` or `npm run dev`

4. Open **http://localhost:3000** – marketing home (public). Log in to access **Dashboard** (Nuvatra Voice).

### Run servers separately (optional)

- **Backend:** `cd backend && python main.py` (port 8000)
- **Frontend:** `npm run dev` (port 3000)

### Troubleshooting

- **Port 8000 in use (Windows):** `Get-NetTCPConnection -LocalPort 8000 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }`
- **Frontend stuck on "Starting...":** Stop, then `Remove-Item -Path .next -Recurse -Force`, then `npm run dev` again

### Testing

- **Web:** Open http://localhost:3000 → sign in → Appointments / Dashboard / Settings. Use Settings to set voice and store info.
- **Phone:** Deploy backend, point Twilio webhooks to `https://your-backend-url/api/phone/incoming` and `.../api/phone/status`, then call your Twilio number. See [PHONE-SETUP.md](./PHONE-SETUP.md).

## Documentation

| Doc | Description |
|-----|-------------|
| [AUTH-SETUP.md](./AUTH-SETUP.md) | Clerk – sign up, API keys, protect dashboard |
| [PHONE-SETUP.md](./PHONE-SETUP.md) | Twilio: number, webhooks, ngrok for local |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Deploy backend (Render/Railway) and frontend (Vercel) |
| [INVITE-ONLY-SETUP.md](./INVITE-ONLY-SETUP.md) | Invite-only sign-up, admin flow, multi-tenant |
| [clients/README.md](./clients/README.md) | Client config structure and adding new clients |

## Configuration

- **Backend**: Client config in `clients/<client-id>/config.json`; set `CLIENT_ID` env or use demo config.
- **Business copy**: Edit config for business name, hours, services, staff, and reservation rules.

## License

MIT
