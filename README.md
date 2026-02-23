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

## Quick Start

**Prerequisites:** Node.js 18+, Python 3.9+, OpenAI API key

1. **Install**
   ```bash
   npm install
   pip install -r backend/requirements.txt
   ```

2. **Environment**  
   Create `backend/.env` (and optionally root `.env.local`):
   ```env
   OPENAI_API_KEY=your_openai_api_key
   ```
   For the frontend, set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `.env.local` if needed.

3. **Run both servers (one command)**
   - Windows: `bin\dev.cmd` or `npm run dev`
   - Mac/Linux: `./bin/dev` or `npm run dev`

4. Open **http://localhost:3000** and click **Voice Call** to try the web interface.

See **[QUICK-START.md](./QUICK-START.md)** for running backend and frontend in separate terminals and troubleshooting.

## Documentation

| Doc | Description |
|-----|-------------|
| [QUICK-START.md](./QUICK-START.md) | Run servers, open app, basic troubleshooting |
| [PHONE-SETUP.md](./PHONE-SETUP.md) | Twilio: number, webhooks, ngrok for local testing |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Deploy backend (Railway, Render) and optional frontend (Vercel) |
| [CLIENT-SETUP.md](./CLIENT-SETUP.md) | Add a new client: config, onboarding checklist |
| [TESTING-GUIDE.md](./TESTING-GUIDE.md) | Test web and phone flows |
| [PROTOTYPE-SETUP.md](./PROTOTYPE-SETUP.md) | **Prototype number 925-481-5386** – Twilio webhooks, env, SMS, what you need to provide |
| [PLANS-AND-FEATURES.md](./PLANS-AND-FEATURES.md) | **Starter / Growth / Pro** – feature matrix and what’s implemented vs roadmap |
| [clients/README.md](./clients/README.md) | Client config structure and options |

## Configuration

- **Backend**: Client config in `clients/<client-id>/config.json`; set `CLIENT_ID` env or use demo config.
- **Business copy**: Edit config for business name, hours, services, staff, and reservation rules.

## License

MIT
