# ============================================
# VERSION MARKER: 2025-12-08-07:10 - PINNED VERSIONS
# If you see this, Railway is running NEW code
# ============================================
print("=" * 60)
print("DEBUG: NEW CODE LOADED - Version 2025-12-08-07:10")
print("DEBUG: Using openai==1.40.0 and httpx==0.27.0")
print("=" * 60)
import sys
sys.stdout.flush()

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
# Debug: Check installed versions BEFORE creating client
print("=" * 50)
print("DEBUG: Starting OpenAI client initialization...")
print("=" * 50)

# Check which requirements.txt files exist
import pathlib
root_req = pathlib.Path("/app/requirements.txt")
backend_req = pathlib.Path("/app/backend/requirements.txt")
current_req = _backend_dir / "requirements.txt"
print(f"DEBUG: Checking requirements.txt files:")
print(f"  /app/requirements.txt exists: {root_req.exists()}")
print(f"  /app/backend/requirements.txt exists: {backend_req.exists()}")
print(f"  {current_req} exists: {current_req.exists()}")
if root_req.exists():
    print(f"  /app/requirements.txt content (first 5 lines):")
    with open(root_req, 'r') as f:
        for i, line in enumerate(f):
            if i < 5:
                print(f"    {line.strip()}")
if backend_req.exists():
    print(f"  /app/backend/requirements.txt content (first 5 lines):")
    with open(backend_req, 'r') as f:
        for i, line in enumerate(f):
            if i < 5:
                print(f"    {line.strip()}")
print("=" * 50)

try:
    import httpx
    import openai
    import sys
    import subprocess
    print(f"DEBUG: Python version: {sys.version}")
    print(f"DEBUG: httpx version: {httpx.__version__}")
    print(f"DEBUG: openai version: {openai.__version__}")
    print(f"DEBUG: httpx location: {httpx.__file__}")
    print(f"DEBUG: openai location: {openai.__file__}")
    
    # Check what pip actually installed
    try:
        result = subprocess.run(['pip', 'list'], capture_output=True, text=True, timeout=5)
        print("DEBUG: Installed packages (pip list):")
        for line in result.stdout.split('\n')[:20]:  # First 20 lines
            if 'openai' in line.lower() or 'httpx' in line.lower():
                print(f"  {line}")
    except Exception as e:
        print(f"DEBUG: Could not run pip list: {e}")
    
    # Check httpx.Client signature
    import inspect
    try:
        sig = inspect.signature(httpx.Client.__init__)
        print(f"DEBUG: httpx.Client.__init__ signature: {sig}")
        print(f"DEBUG: httpx.Client.__init__ parameters: {list(sig.parameters.keys())}")
    except Exception as e:
        print(f"DEBUG: Error inspecting httpx.Client: {e}")
    
    # Check if 'proxies' is in the signature
    if hasattr(httpx.Client.__init__, '__code__'):
        params = inspect.signature(httpx.Client.__init__).parameters
        has_proxies = 'proxies' in params
        print(f"DEBUG: httpx.Client.__init__ has 'proxies' parameter: {has_proxies}")
    
except Exception as e:
    print(f"DEBUG: Error checking versions: {e}")
    import traceback
    traceback.print_exc()

print("DEBUG: About to create OpenAI client...")
sys.stdout.flush()

# Try to create client with detailed error handling
try:
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    print("DEBUG: OpenAI client created successfully!")
except Exception as e:
    print(f"DEBUG: ERROR creating OpenAI client: {e}")
    print(f"DEBUG: Error type: {type(e)}")
    import traceback
    print("DEBUG: Full traceback:")
    traceback.print_exc()
    sys.stdout.flush()
    raise  # Re-raise to see the error in logs

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

def get_twilio_language_code(language_name: str) -> str:
    """
    Map language name to Twilio language code for speech recognition.
    Returns Twilio language code (e.g., 'es-ES', 'en-US', 'hi-IN').
    Defaults to 'en-US' if language not supported.
    """
    language_map = {
        'English': 'en-US',
        'Spanish': 'es-ES',
        'French': 'fr-FR',
        'German': 'de-DE',
        'Italian': 'it-IT',
        'Portuguese': 'pt-PT',
        'Chinese': 'zh-CN',
        'Japanese': 'ja-JP',
        'Korean': 'ko-KR',
        'Hindi': 'hi-IN',
        'Punjabi': 'pa-IN',  # Punjabi (Gurmukhi)
        'Arabic': 'ar-SA',
        'Russian': 'ru-RU',
        'Dutch': 'nl-NL',
        'Polish': 'pl-PL',
        'Turkish': 'tr-TR',
        'Swedish': 'sv-SE',
        'Norwegian': 'nb-NO',
        'Danish': 'da-DK',
        'Finnish': 'fi-FI',
        'Greek': 'el-GR',
        'Czech': 'cs-CZ',
        'Romanian': 'ro-RO',
        'Hungarian': 'hu-HU',
        'Thai': 'th-TH',
        'Vietnamese': 'vi-VN',
        'Indonesian': 'id-ID',
        'Malay': 'ms-MY',
    }
    
    # Try exact match first
    if language_name in language_map:
        return language_map[language_name]
    
    # Try case-insensitive match
    for key, code in language_map.items():
        if key.lower() == language_name.lower():
            return code
    
    # Default to English if not found
    return 'en-US'

def detect_language(text: str) -> str:
    """
    Detect the language of the input text using OpenAI's intelligence.
    Returns language name in English (e.g., 'Spanish', 'Punjabi', 'English', 'French', etc.).
    This function is called on EVERY speech input to support dynamic language switching.
    Relies on OpenAI to detect any language automatically - no hardcoded word lists.
    """
    if not text or len(text.strip()) < 3:
        return "English"
    
    # Use OpenAI to detect language - it can detect any language automatically
    try:
        # Check if client is available
        if 'client' not in globals() or client is None:
            return "English"
        
        # Use OpenAI to intelligently detect the language
        # This works for any language, not just hardcoded ones
        detection_prompt = f"""Detect the language of this text and respond with ONLY the language name in English (e.g., 'Spanish', 'Punjabi', 'English', 'French', 'German', 'Chinese', 'Hindi', 'Italian', 'Portuguese', 'Japanese', 'Korean', 'Arabic', 'Russian', etc.). 

Text: {text[:200]}

Respond with just the language name, nothing else."""
        
        detection_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": detection_prompt}],
            max_tokens=15,
            temperature=0  # Low temperature for consistent language detection
        )
        detected_lang = detection_response.choices[0].message.content.strip()
        
        # Clean up response (remove quotes, extra words, periods)
        detected_lang = detected_lang.replace('"', '').replace("'", "").replace('.', '').strip()
        
        # Extract just the language name (in case GPT adds extra text)
        # Take the first word which should be the language name
        detected_lang = detected_lang.split()[0] if detected_lang.split() else detected_lang
        
        # Capitalize first letter (e.g., "spanish" -> "Spanish")
        if detected_lang:
            detected_lang = detected_lang.capitalize()
        
        if detected_lang and len(detected_lang) < 30:  # Sanity check
            return detected_lang
    except Exception as e:
        print(f"Language detection error: {e}")
        import traceback
        traceback.print_exc()
    
    # Default to English if detection fails
    return "English"

def get_system_prompt(detected_language: str = "English"):
    # Ultra-concise prompt for fastest processing while maintaining peppy, warm tone
    # CRITICAL: Respond ONLY in the detected language (language can change mid-conversation)
    base_prompt = f"""Super peppy, warm AI receptionist for {BUSINESS_INFO['name']}! Be EXTRA POSITIVE and ENTHUSIASTIC! Use peppy phrases like "absolutely!", "wonderful!", "awesome!". Keep responses to 1 sentence max. Be warm, brief, and make callers feel amazing! Help with: questions (hours: {BUSINESS_INFO['hours']}), appointments, messages, routing to {', '.join(BUSINESS_INFO['departments'])}."""
    
    if detected_language != "English":
        return f"""{base_prompt} CRITICAL INSTRUCTION: The caller is currently speaking in {detected_language}. You MUST respond ONLY in {detected_language}. Do NOT respond in English or any other language. Every word of your response must be in {detected_language}. If the caller switches languages, adapt immediately and respond in their new language."""
    else:
        return f"""{base_prompt} IMPORTANT: Respond in English. If the caller switches to another language, detect it and respond in that language immediately."""

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
            "detected_language": None,  # Will be detected from first speech input
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
        greeting_text = "Hello! Thank you for calling. This is your personal AI receptionist. I'm here to help you today. Please note that it may take a couple seconds for me to process what you say, so please bear with me but I will try my best to give you the best experience! How can I assist you?"
        
        # Use HD TTS endpoint for the greeting to ensure it's ultra-smooth (no choppiness)
        # Generate audio URL that Twilio can play
        greeting_encoded = quote(greeting_text)
        tts_audio_url = f"{base_url}/api/phone/tts-audio-hd?text={greeting_encoded}&voice=fable"
        response.play(tts_audio_url)
        
        # Gather voice input from caller - start with English, will adapt based on detected language
        gather = response.gather(
            input='speech',
            action=f"{base_url}/api/phone/process-speech",
            method='POST',
            speech_timeout='auto',
            language='en-US',  # Start with English, will be updated dynamically after first detection
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
        
        # Always detect language from current speech input to support dynamic language switching
        # This allows the AI to adapt whenever the caller switches languages, no matter how many times
        # (e.g., if someone hands the phone to another person who speaks a different language,
        # or if the same person switches between languages)
        current_detected_lang = detect_language(speech_result)
        previous_lang = call_data.get("detected_language")
        
        # Always use the currently detected language (not stored one) to ensure real-time switching
        # Update stored language whenever it changes (supports unlimited language switches)
        if previous_lang != current_detected_lang:
            if previous_lang:
                print(f"🌍 Language switched: {previous_lang} -> {current_detected_lang} from text: {speech_result[:50]}")
            else:
                print(f"🌍 Detected language: {current_detected_lang} from text: {speech_result[:50]}")
            call_data["detected_language"] = current_detected_lang
        else:
            print(f"🌍 Using language: {current_detected_lang} (unchanged)")
        
        # Always use the freshly detected language (not the stored one) to ensure immediate switching
        detected_lang = current_detected_lang
        
        # Add user message to conversation
        user_message = {
            "role": "user",
            "content": speech_result
        }
        call_data["conversation_history"].append(user_message)
        
        # Get AI response - use faster model for phone calls
        # Use detected language in system prompt to ensure AI responds in that language
        messages = [
            {"role": "system", "content": get_system_prompt(detected_lang)}
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
        
        # Use the same base_url for gather action - set language dynamically based on detected language
        # This helps Twilio transcribe speech more accurately in the caller's language
        twilio_lang_code = get_twilio_language_code(detected_lang)
        print(f"🌍 Setting Twilio language to: {twilio_lang_code} (for {detected_lang})")
        
        gather = response.gather(
            input='speech',
            action=f"{base_url}/api/phone/process-speech",
            method='POST',
            speech_timeout='auto',
            language=twilio_lang_code  # Set language dynamically for better transcription
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
        
        # Transcribe using OpenAI Whisper - auto-detect language for multi-language support
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=temp_file
            # language parameter omitted to allow auto-detection of any language
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

