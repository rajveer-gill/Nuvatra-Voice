# Nuvatra Voice - AI Voice Receptionist

An intelligent AI-powered voice receptionist system for businesses that can handle calls, schedule appointments, take messages, and route inquiries.

## Features

- 🎤 **Voice Interaction**: Real-time speech-to-text and text-to-speech
- 🤖 **AI-Powered**: Uses OpenAI GPT for natural conversations
- 📅 **Appointment Scheduling**: Manage and schedule appointments
- 💬 **Message Taking**: Record and store messages
- 🔄 **Call Routing**: Intelligently route calls to appropriate departments
- 📊 **Dashboard**: Monitor calls and interactions
- 🎨 **Modern UI**: Beautiful, responsive interface

## Tech Stack

- **Frontend**: Next.js 14, React, TypeScript, Tailwind CSS
- **Backend**: Python FastAPI
- **AI**: OpenAI GPT-4
- **Voice**: Web Speech API (browser-based)

## Setup

### Prerequisites

- Node.js 18+ and npm
- Python 3.9+
- OpenAI API key

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

