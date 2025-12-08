from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional, List
import openai
import os
from dotenv import load_dotenv
from datetime import datetime
import json
from pathlib import Path
import io
from urllib.parse import quote
# Twilio imports (optional - only needed for phone integration)
try:
    from twilio.twiml.voice_response import VoiceResponse
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    print("WARNING: Twilio not installed - phone features will be disabled. Install with: pip install twilio")

# Load .env from backend directory (where this script is located)
# Get the directory where this script is located
_this_file = Path(__file__).resolve()
_backend_dir = _this_file.parent

# The .env file is in the backend directory
env_path = _backend_dir / '.env'

# Load .env file
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    # Fallback: try default load_dotenv behavior
    load_dotenv()

# Verify API key is loaded
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print(f"ERROR: OPENAI_API_KEY not found!")
    print(f"Checked path: {env_path}")
    print(f"Path exists: {env_path.exists()}")
    print(f"Make sure your .env file is in the backend directory with OPENAI_API_KEY=your_key")
    raise ValueError(
        f"OPENAI_API_KEY not found! Checked: {env_path}\n"
        f"Make sure your .env file is in the backend directory with OPENAI_API_KEY=your_key"
    )
else:
    print(f"API Key loaded successfully (length: {len(api_key)})")

app = FastAPI(title="Nuvatra Voice API")

# CORS middleware
# CORS configuration - allow localhost for development and production frontend
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# Add production frontend URL if set
frontend_url = os.getenv("FRONTEND_URL")
if frontend_url:
    allowed_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize Twilio (optional - only if credentials are provided)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

twilio_client = None
if TWILIO_AVAILABLE and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        print(f"Twilio initialized successfully")
    except Exception as e:
        print(f"WARNING: Twilio initialization failed: {e}")
elif not TWILIO_AVAILABLE:
    print("WARNING: Twilio not installed - phone features disabled. Install with: pip install twilio")
elif not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
    print("WARNING: Twilio credentials not found - phone features will be disabled")

# In-memory storage (replace with database in production)
appointments = []
messages = []
conversation_history = {}

# Business configuration
BUSINESS_INFO = {
    "name": "Your Business",
    "hours": "Monday-Friday: 9 AM - 5 PM",
    "phone": "(555) 123-4567",
    "email": "info@yourbusiness.com",
    "departments": ["Sales", "Support", "Billing", "General"]
}

class ConversationRequest(BaseModel):
    message: str
    session_id: str
    conversation_history: Optional[List[dict]] = []

class ConversationResponse(BaseModel):
    response: str
    action: Optional[str] = None
    data: Optional[dict] = None

class AppointmentRequest(BaseModel):
    name: str
    email: str
    phone: str
    date: str
    time: str
    reason: str

class MessageRequest(BaseModel):
    caller_name: str
    caller_phone: str
    message: str
    urgency: str = "normal"

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "fable"  # nova, alloy, echo, fable, onyx, shimmer

def get_system_prompt():
    # Ultra-concise prompt for fastest processing while maintaining peppy, warm tone
    return f"""Super peppy, warm AI receptionist for {BUSINESS_INFO['name']}! Be EXTRA POSITIVE and ENTHUSIASTIC! Use peppy phrases like "absolutely!", "wonderful!", "awesome!". Keep responses to 1 sentence max. Be warm, brief, and make callers feel amazing! Help with: questions (hours: {BUSINESS_INFO['hours']}), appointments, messages, routing to {', '.join(BUSINESS_INFO['departments'])}."""

@app.get("/")
async def root():
    return {"message": "Nuvatra Voice API", "status": "running"}

@app.post("/api/conversation", response_model=ConversationResponse)
async def handle_conversation(request: ConversationRequest):
    try:
        # Build conversation messages
        messages = [
            {"role": "system", "content": get_system_prompt()}
        ]
        
        # Add conversation history
        if request.conversation_history:
            messages.extend(request.conversation_history)
        
        # Add current message
        messages.append({"role": "user", "content": request.message})
        
        # Call OpenAI - use gpt-3.5-turbo for faster responses
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Faster response time while maintaining quality
            messages=messages,
            temperature=0.7,
            max_tokens=200
        )
        
        ai_response = response.choices[0].message.content
        
        # Detect actions in the response
        action = None
        data = None
        
        # Simple action detection (can be enhanced with function calling)
        if "schedule" in request.message.lower() or "appointment" in request.message.lower():
            action = "schedule_appointment"
        elif "message" in request.message.lower() or "leave a message" in request.message.lower():
            action = "take_message"
        elif "transfer" in request.message.lower() or "department" in request.message.lower():
            action = "route_call"
        
        return ConversationResponse(
            response=ai_response,
            action=action,
            data=data
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/appointments")
async def create_appointment(appointment: AppointmentRequest):
    try:
        appointment_data = {
            "id": len(appointments) + 1,
            **appointment.dict(),
            "created_at": datetime.now().isoformat(),
            "status": "pending"
        }
        appointments.append(appointment_data)
        return {"success": True, "appointment": appointment_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/appointments")
async def get_appointments():
    return {"appointments": appointments}

@app.post("/api/messages")
async def create_message(message: MessageRequest):
    try:
        message_data = {
            "id": len(messages) + 1,
            **message.dict(),
            "created_at": datetime.now().isoformat(),
            "status": "unread"
        }
        messages.append(message_data)
        return {"success": True, "message": message_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/messages")
async def get_messages():
    return {"messages": messages}

@app.get("/api/business-info")
async def get_business_info():
    return BUSINESS_INFO

@app.get("/api/stats")
async def get_stats():
    return {
        "total_appointments": len(appointments),
        "total_messages": len(messages),
        "pending_appointments": len([a for a in appointments if a["status"] == "pending"])
    }

@app.post("/api/text-to-speech")
async def text_to_speech(request: TTSRequest):
    """
    Convert text to speech using OpenAI's TTS API.
    Returns audio file as streaming response.
    Available voices: alloy, echo, fable, onyx, nova, shimmer
    """
    try:
        # Generate speech using OpenAI TTS HD model for maximum quality
        response = client.audio.speech.create(
            model="tts-1-hd",  # HD model for smooth, natural, human-like quality
            voice=request.voice,
            input=request.text,
            speed=0.92  # Slightly slower for smooth, natural flow
        )
        
        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)
        
        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3"
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Phone call storage (in production, use a database)
active_calls = {}  # {call_sid: {session_id, conversation_history, stream_sid}}

@app.post("/api/phone/incoming")
async def handle_incoming_call(request: Request):
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed. Install with: pip install twilio")
    """
    Twilio webhook for incoming phone calls.
    This endpoint is called when someone calls your Twilio phone number.
    """
    try:
        # Log the incoming request for debugging
        print(f"Incoming call webhook received from: {request.client.host if request.client else 'unknown'}")
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        from_number = form_data.get("From")
        to_number = form_data.get("To")
        
        print(f"📞 Incoming call: {from_number} -> {to_number} (CallSid: {call_sid})")
        
        # Create a new session for this call
        session_id = f"phone-{call_sid}"
        active_calls[call_sid] = {
            "session_id": session_id,
            "from_number": from_number,
            "to_number": to_number,
            "conversation_history": [],
            "started_at": datetime.now().isoformat()
        }
        
        # Create TwiML response
        response = VoiceResponse()
        
        # Get base URL - use the ngrok URL from environment or construct from request
        # For ngrok, we need to use the public URL, not localhost
        base_url = os.getenv("NGROK_URL")
        if not base_url:
            # Fallback: try to get from request, but replace localhost with ngrok domain if present
            request_url = str(request.url)
            if "ngrok" in request_url:
                base_url = request_url.replace("/api/phone/incoming", "")
            else:
                # Default to ngrok URL format (user should set NGROK_URL env var)
                base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
        
        # Generate greeting with OpenAI TTS - use HD model for ultra-smooth initial greeting
        greeting_text = "Hi there! Thanks so much for calling! I'm really excited to help you today! What can I do for you?"
        
        # Use HD TTS endpoint for the greeting to ensure it's ultra-smooth (no choppiness)
        # Generate audio URL that Twilio can play
        greeting_encoded = quote(greeting_text)
        tts_audio_url = f"{base_url}/api/phone/tts-audio-hd?text={greeting_encoded}&voice=fable"
        response.play(tts_audio_url)
        
        # Gather voice input from caller
        gather = response.gather(
            input='speech',
            action=f"{base_url}/api/phone/process-speech",
            method='POST',
            speech_timeout='auto',
            language='en-US',
            hints='appointment, schedule, message, hours, contact, help'
        )
        
        # If no input, redirect to process speech anyway
        response.redirect(f"{base_url}/api/phone/process-speech", method='POST')
        
        return Response(content=str(response), media_type="application/xml")
    
    except Exception as e:
        print(f"Error handling incoming call: {e}")
        response = VoiceResponse()
        # Use OpenAI TTS for error message
        error_text = "I'm sorry, I'm having technical difficulties. Please try again later."
        base_url = os.getenv("NGROK_URL") or "https://gwenda-denumerable-cami.ngrok-free.dev"
        error_encoded = quote(error_text)
        tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice=fable"
        response.play(tts_audio_url)
        return Response(content=str(response), media_type="application/xml")

@app.post("/api/phone/process-speech")
async def process_speech(request: Request):
    if not TWILIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Twilio not installed. Install with: pip install twilio")
    """
    Process speech input from phone call and generate AI response.
    """
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        speech_result = form_data.get("SpeechResult", "")
        confidence = form_data.get("Confidence", "0")
        
        print(f"🎤 Speech received: {speech_result} (confidence: {confidence})")
        
        if not call_sid or call_sid not in active_calls:
            response = VoiceResponse()
            response.say("I'm sorry, I lost track of our conversation. Please call back.", voice='alice')
            return Response(content=str(response), media_type="application/xml")
        
        call_data = active_calls[call_sid]
        
        # Add user message to conversation
        user_message = {
            "role": "user",
            "content": speech_result
        }
        call_data["conversation_history"].append(user_message)
        
        # Get AI response - use faster model for phone calls
        messages = [
            {"role": "system", "content": get_system_prompt()}
        ]
        messages.extend(call_data["conversation_history"])
        
        # Use gpt-3.5-turbo with aggressive optimizations for ultra-fast responses
        ai_response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Fastest quality model
            messages=messages,
            temperature=0.8,  # Slightly higher for more natural responses
            max_tokens=80,  # Very brief for phone - faster generation
            stream=False
        )
        
        ai_text = ai_response.choices[0].message.content
        
        # Add AI response to conversation
        ai_message = {
            "role": "assistant",
            "content": ai_text
        }
        call_data["conversation_history"].append(ai_message)
        
        # Create TwiML response
        response = VoiceResponse()
        
        # Use OpenAI TTS for premium voice quality
        base_url = os.getenv("NGROK_URL")
        if not base_url:
            request_url = str(request.url)
            if "ngrok" in request_url:
                base_url = request_url.replace("/api/phone/process-speech", "")
            else:
                base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
        
        # Generate audio URL for AI response using OpenAI TTS
        ai_text_encoded = quote(ai_text)
        tts_audio_url = f"{base_url}/api/phone/tts-audio?text={ai_text_encoded}&voice=fable"
        response.play(tts_audio_url)
        
        # Use the same base_url for gather action
        gather = response.gather(
            input='speech',
            action=f"{base_url}/api/phone/process-speech",
            method='POST',
            speech_timeout='auto',
            language='en-US'
        )
        
        # If no input, say goodbye
        response.say("Thanks for calling! Have a wonderful day!", voice='alice')
        response.hangup()
        
        return Response(content=str(response), media_type="application/xml")
    
    except Exception as e:
        print(f"Error processing speech: {e}")
        response = VoiceResponse()
        # Use OpenAI TTS for error message too
        error_text = "I'm sorry, I didn't catch that. Could you repeat?"
        base_url = os.getenv("NGROK_URL")
        if not base_url:
            request_url = str(request.url)
            if "ngrok" in request_url:
                base_url = request_url.replace("/api/phone/process-speech", "")
            else:
                base_url = "https://gwenda-denumerable-cami.ngrok-free.dev"
        error_encoded = quote(error_text)
        tts_audio_url = f"{base_url}/api/phone/tts-audio?text={error_encoded}&voice=fable"
        response.play(tts_audio_url)
        response.redirect(f"{base_url}/api/phone/process-speech", method='POST')
        return Response(content=str(response), media_type="application/xml")

@app.post("/api/phone/status")
async def handle_call_status(request: Request):
    """
    Twilio webhook for call status updates (call ended, etc.)
    """
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")
        
        print(f"📞 Call status update: {call_sid} -> {call_status}")
        
        # Clean up when call ends
        if call_status in ["completed", "failed", "busy", "no-answer", "canceled"]:
            if call_sid in active_calls:
                del active_calls[call_sid]
                print(f"Cleaned up call session: {call_sid}")
        
        return Response(content="OK", media_type="text/plain")
    
    except Exception as e:
        print(f"Error handling call status: {e}")
        return Response(content="OK", media_type="text/plain")

@app.post("/api/phone/stream")
async def handle_media_stream(request: Request):
    """
    WebSocket endpoint for Twilio Media Streams.
    This handles real-time bidirectional audio streaming.
    """
    # This is a simplified version - full implementation requires WebSocket handling
    # For production, you'd use a WebSocket library like 'websockets' or 'fastapi-websocket'
    return {"message": "Media stream endpoint - requires WebSocket implementation"}

@app.get("/api/phone/tts-audio-hd")
async def get_tts_audio_hd_for_phone(text: str, voice: str = "fable"):
    """
    Generate HD TTS audio for Twilio phone calls (ultra-smooth, no choppiness).
    Used specifically for the initial greeting to ensure perfect quality.
    """
    try:
        # Use tts-1-hd for ultra-smooth, natural speech (no choppiness)
        response = client.audio.speech.create(
            model="tts-1-hd",  # HD model for ultra-smooth, natural speech
            voice=voice,
            input=text,
            speed=0.90  # Slightly slower for ultra-smooth flow
        )
        
        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)
        
        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Cache-Control": "no-cache"
            }
        )
    except Exception as e:
        print(f"Error generating HD TTS audio: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate HD TTS audio: {str(e)}")

@app.get("/api/phone/tts-audio")
async def get_tts_audio_for_phone(text: str, voice: str = "fable"):
    """
    Generate TTS audio for phone calls.
    This endpoint is called by Twilio to play OpenAI TTS audio.
    """
    try:
        # Use tts-1 for faster generation while maintaining quality
        # tts-1 is faster than tts-1-hd but still sounds natural and smooth
        response = client.audio.speech.create(
            model="tts-1",  # Faster generation, still high quality
            voice=voice,
            input=text,
            speed=0.92  # Natural pace for smooth flow
        )
        
        # Convert response to bytes
        audio_bytes = io.BytesIO(response.content)
        audio_bytes.seek(0)
        
        # Return as streaming audio
        return StreamingResponse(
            audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Cache-Control": "no-cache"
            }
        )
    
    except Exception as e:
        print(f"TTS audio generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/phone/transcribe")
async def transcribe_phone_audio(audio_data: str = Form(...)):
    """
    Transcribe audio from phone call using OpenAI Whisper.
    This endpoint receives base64-encoded audio from Twilio.
    """
    try:
        # Decode base64 audio
        audio_bytes = base64.b64decode(audio_data)
        
        # Save to temporary file
        temp_file = io.BytesIO(audio_bytes)
        temp_file.name = "audio.webm"
        
        # Transcribe using OpenAI Whisper
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=temp_file,
            language="en"
        )
        
        return {"transcript": transcript.text}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/phone/calls")
async def get_active_calls():
    """Get list of active phone calls"""
    return {
        "active_calls": len(active_calls),
        "calls": [
            {
                "call_sid": sid,
                "from": call_data["from_number"],
                "to": call_data["to_number"],
                "started_at": call_data["started_at"]
            }
            for sid, call_data in active_calls.items()
        ]
    }

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("Starting Nuvatra Voice Backend Server")
    print("="*50)
    print(f"Server will run on: http://0.0.0.0:8000")
    print(f"Local access: http://localhost:8000")
    print("="*50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

