# Nuvatra Voice - AI Voice Receptionist

An intelligent AI-powered voice receptionist system for businesses that can handle calls, schedule appointments, take messages, and route inquiries.

## Features

- 🎤 **Voice Interaction**: Real-time speech-to-text and text-to-speech
- 📞 **Phone Integration**: Answer real phone calls via Twilio
- 🤖 **AI-Powered**: Uses OpenAI GPT for natural conversations
- 🎙️ **Premium Voices**: Ultra-natural AI voices using OpenAI TTS-1-HD
- 📅 **Appointment Scheduling**: Manage and schedule appointments
- 💬 **Message Taking**: Record and store messages
- 🔄 **Call Routing**: Intelligently route calls to appropriate departments
- 📊 **Dashboard**: Monitor calls and interactions
- 🎨 **Modern UI**: Beautiful, responsive interface

## Tech Stack

- **Frontend**: Next.js 14, React, TypeScript, Tailwind CSS
- **Backend**: Python FastAPI
- **AI**: OpenAI GPT-4
- **Voice**: OpenAI TTS-1-HD (premium AI voices)
- **Phone**: Twilio (for phone call integration)
- **Browser Voice**: Web Speech API (for web interface)

## Setup

### Prerequisites

- Node.js 18+ and npm
- Python 3.9+
- OpenAI API key
- (Optional) Twilio account for phone integration

### Installation

1. **Install frontend dependencies:**
   ```bash
   npm install
   ```

2. **Install backend dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**
   
   Create `.env.local` in the root directory:
   ```
   OPENAI_API_KEY=your_openai_api_key_here
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```
   
   Also create `.env` in the `backend` directory (or use the root `.env.local`):
   ```
   OPENAI_API_KEY=your_openai_api_key_here
   ```

4. **Start the backend server:**
   
   Open a terminal and run:
   ```bash
   cd backend
   python main.py
   ```
   
   You should see:
   ```
   ✓ API Key loaded successfully
   INFO:     Uvicorn running on http://0.0.0.0:8000
   ```
   
   **Keep this terminal open!**

5. **Start the frontend:**
   
   Open a **NEW** terminal and run:

## Phone Integration

To enable phone call functionality, see [PHONE-SETUP.md](./PHONE-SETUP.md) for detailed instructions on setting up Twilio integration.

**Quick Start:**
1. Sign up for a Twilio account
2. Purchase a phone number
3. Add Twilio credentials to `backend/.env`
4. Configure webhooks in Twilio Console
5. Call your number to test!

## Usage

### Web Interface

1. Open http://localhost:3000
2. Click "Start Call"
3. Speak naturally - the AI will respond with premium voice quality

### Phone Calls

1. Set up Twilio (see PHONE-SETUP.md)
2. Call your Twilio phone number
3. The AI receptionist will answer and assist you

## Development

5. **Start the frontend:**
   
   Open a **NEW** terminal and run:
   ```powershell
   # Refresh PATH (Windows PowerShell only)
   $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
   
   # Clear Next.js cache if needed
   Remove-Item -Path .next -Recurse -Force -ErrorAction SilentlyContinue
   
   # Start the frontend
   npm run dev
   ```
   
   You should see:
   ```
   ✓ Ready in XXXXms
   - Local:        http://localhost:3000
   ```
   
   **Keep this terminal open!**

6. **Open your browser:**
   Navigate to `http://localhost:3000`

## Usage

1. Click "Start Call" to begin a conversation
2. The AI receptionist will greet the caller
3. Speak naturally - the system will understand and respond
4. The receptionist can:
   - Schedule appointments
   - Take messages
   - Answer questions about your business
   - Route calls to departments

## Configuration

Edit `backend/config.py` to customize:
- Business information
- Available departments
- Business hours
- Default responses

## License

MIT

