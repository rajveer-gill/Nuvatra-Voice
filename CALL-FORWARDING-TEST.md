# Call Forwarding Test Guide

## ✅ What Was Added

Call forwarding functionality has been implemented! The AI will now:
1. **Forward when user requests** - If user says "I want to talk to a person" or similar
2. **Forward on errors** - If there's a technical error, it forwards to the business phone
3. **Multi-language support** - Forwarding messages work in Spanish, French, and English

---

## 🔧 Setup Required

### 1. Set Forwarding Phone Number

You need to set the business phone number that calls will be forwarded to.

**Option A: Environment Variable (Recommended)**
```bash
BUSINESS_FORWARDING_PHONE=+15551234567
```

**Option B: Update in Code**
Edit `backend/main.py` line ~283:
```python
"forwarding_phone": os.getenv("BUSINESS_FORWARDING_PHONE", "+15551234567"),  # Your actual phone here
```

**Phone Format:**
- Must be in E.164 format: `+1XXXXXXXXXX`
- Example: `+15551234567` (US number)
- The system will auto-format if you provide it in other formats

---

## 🧪 Testing Call Forwarding

### Test 1: User Requests to Talk to a Person

**What to say:**
- "I want to talk to a person"
- "Can I speak to someone?"
- "Transfer me to a real person"
- "I need to talk to a human"
- "Connect me with someone"

**Expected behavior:**
1. AI detects the request
2. Says: "Connecting you with someone now. Please hold."
3. Forwards call to business phone number
4. If no answer: "I'm sorry, no one is available right now. Please try again later or leave a message."

---

### Test 2: Error Handling (Forward on Error)

**How to test:**
- This is harder to trigger manually, but if the AI has a technical error, it should forward

**Expected behavior:**
1. Error occurs
2. AI says: "I'm experiencing technical difficulties. Let me connect you with someone who can help."
3. Forwards to business phone

---

### Test 3: Multi-Language Forwarding

**Test in Spanish:**
- Say: "Quiero hablar con una persona"
- Should forward with Spanish message: "Conectándote con alguien ahora. Por favor espera."

**Test in French:**
- Say: "Je veux parler à quelqu'un"
- Should forward with French message: "Je vous connecte maintenant. Veuillez patienter."

---

## 📋 Quick Test Checklist

Before going live, test:

- [ ] Forwarding phone number is set correctly
- [ ] Test forwarding by saying "I want to talk to a person"
- [ ] Verify call connects to business phone
- [ ] Test what happens if business phone doesn't answer (should get message)
- [ ] Test in Spanish (if applicable)
- [ ] Verify forwarding works from any point in conversation

---

## 🔍 Debugging

**If forwarding doesn't work:**

1. **Check phone number format:**
   - Should be: `+15551234567`
   - Not: `(555) 123-4567` or `555-123-4567`

2. **Check logs:**
   - Look for: `🔄 Forwarding call to business phone: +1...`
   - Look for: `📞 Forwarding call to business: +1...`

3. **Check environment variable:**
   - Make sure `BUSINESS_FORWARDING_PHONE` is set in your deployment

4. **Test phone number:**
   - Make sure the forwarding number can receive calls
   - Test calling it directly first

---

## 💡 Pro Tips

1. **Use a real phone number for testing** - Don't use a fake number
2. **Test during business hours** - Make sure someone can answer
3. **Test the "no answer" scenario** - Call when no one is available
4. **Document the forwarding number** - Keep it in your client config

---

## 🎯 For Sales Demos

**What to tell clients:**
- "If the AI can't help or if a customer wants to talk to a real person, it automatically forwards to your business phone."
- "It also forwards if there's any technical issue, so customers never get stuck."
- "You can set any phone number - your main line, a specific department, or even your cell phone."

---

Ready to test! 🚀

