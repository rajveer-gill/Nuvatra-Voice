# Testing Your AI Receptionist

## Quick Test

### Step 1: Call Your Number
Call: **+1 (925) 481-5386**

### Step 2: What You Should Hear
You should hear the AI say:
> "Hi there! Thanks so much for calling! I'm really excited to help you today! What can I do for you?"

### Step 3: Try a Conversation
Say something like:
- "What are your hours?"
- "I need to schedule an appointment"
- "Can you help me?"

The AI should respond naturally!

---

## Troubleshooting

### If You Don't Hear Anything

1. **Check Railway Logs**:
   - Go to Railway dashboard
   - Click "Logs" tab
   - Look for errors or incoming requests
   - You should see requests when you call

2. **Check Twilio Webhooks**:
   - Make sure URLs are correct:
     - A CALL COMES IN: `https://nuvatra-voice-production.up.railway.app/api/phone/incoming`
     - CALL STATUS: `https://nuvatra-voice-production.up.railway.app/api/phone/status`

3. **Check Environment Variables**:
   - In Railway → Variables tab
   - Make sure all 5 variables are set:
     - OPENAI_API_KEY
     - TWILIO_ACCOUNT_SID
     - TWILIO_AUTH_TOKEN
     - TWILIO_PHONE_NUMBER
     - NGROK_URL

4. **Check Railway Deployment**:
   - Make sure your service is "Active" (green)
   - Check if there are any deployment errors

### If You Hear an Error Message

- Check Railway logs for the specific error
- Verify all environment variables are correct
- Make sure Railway service is running

### If It Works!

✅ Your AI receptionist is live 24/7!  
✅ Businesses can call anytime  
✅ No computer needed  
✅ Fully automated!

---

## What to Look For in Railway Logs

When you call, you should see:
```
🎤 Speech received: [what you said]
INFO: POST /api/phone/incoming
INFO: POST /api/phone/process-speech
```

If you see errors, share them and we can fix them!


