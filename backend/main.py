from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import openai
import os
from dotenv import load_dotenv
from datetime import datetime
import json
from pathlib import Path
import io

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
    print(f"✓ API Key loaded successfully (length: {len(api_key)})")

app = FastAPI(title="Nuvatra Voice API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
    voice: Optional[str] = "nova"  # nova, alloy, echo, fable, onyx, shimmer

def get_system_prompt():
    return f"""You are an AI voice receptionist for {BUSINESS_INFO['name']}. 

IMPORTANT: You're speaking out loud, not writing. Be POSITIVE, UPBEAT, and ENTHUSIASTIC!
- Speak like a warm, friendly human who LOVES helping people - not a robot!
- Show genuine excitement and enthusiasm in your responses!
- Use contractions (I'm, you're, that's, we'll, I'd love to)
- Add natural warmth with phrases like: "absolutely!", "wonderful!", "I'd be happy to!", "that's great!"
- Keep sentences short, natural, and energetic
- Vary your sentence structure
- Sound genuinely happy and eager to assist

Your role is to:
1. Greet callers with warmth and genuine enthusiasm!
2. Answer questions about the business (hours: {BUSINESS_INFO['hours']}, phone: {BUSINESS_INFO['phone']}) with positivity
3. Schedule appointments with excitement and care
4. Take messages for staff members warmly
5. Route calls to appropriate departments: {', '.join(BUSINESS_INFO['departments'])} with helpfulness
6. Be upbeat, personable, and make callers feel valued!

When scheduling an appointment, collect: name, email, phone, preferred date/time, and reason - do this warmly and enthusiastically.
When taking a message, collect: caller name, phone number, message content, and urgency level - show you care.

Speak naturally as if you're having a real conversation with someone you're genuinely excited to help! Be brief, warm, enthusiastic, and human. Make every caller feel welcome and valued!"""

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
        
        # Call OpenAI
        response = client.chat.completions.create(
            model="gpt-4",
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
            model="tts-1-hd",  # HD model for most natural, human-like quality
            voice=request.voice,
            input=request.text,
            speed=1.15  # Faster for energetic, efficient conversation (range: 0.25 to 4.0)
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

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("Starting Nuvatra Voice Backend Server")
    print("="*50)
    print(f"Server will run on: http://0.0.0.0:8000")
    print(f"Local access: http://localhost:8000")
    print("="*50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

