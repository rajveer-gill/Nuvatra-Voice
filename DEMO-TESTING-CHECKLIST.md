# Demo Number Testing Checklist

Use this checklist to test your demo number and ensure everything works perfectly for sales calls.

## 🎯 Quick Test (2 minutes)
**For quick verification before a sales call:**

1. ✅ **Call connects** - No errors, call goes through
2. ✅ **Greeting plays instantly** - No long pause, natural voice (fable voice)
3. ✅ **Basic question answered** - Ask "What are your hours?" → Gets correct answer
4. ✅ **Multi-language works** - Say something in Spanish → AI responds in Spanish

---

## 📋 Full Testing Checklist

### 1. Call Connection & Greeting
- [ ] Call connects without errors
- [ ] Greeting plays **instantly** (no 2-3 second pause)
- [ ] Greeting sounds natural (fable voice, not robotic)
- [ ] Greeting text: "Hello! This is your AI receptionist. It may take a couple seconds to process what you say. How can I help you?"

### 2. FAQ Testing (Restaurant Demo)
Test each of these questions:

**Hours:**
- [ ] "What are your hours?"
- [ ] "When are you open?"
- [ ] "Are you open on Sundays?"

**Location:**
- [ ] "Where are you located?"
- [ ] "What's your address?"

**Menu & Services:**
- [ ] "What's on your menu?"
- [ ] "Do you do delivery?"
- [ ] "Do you offer catering?"
- [ ] "Can I get takeout?"

**Specials:**
- [ ] "What are your specials?"
- [ ] "Do you have happy hour?"
- [ ] "What's your weekend brunch?"

**Reservations:**
- [ ] "Can I make a reservation?"
- [ ] "I need a table for 8 people"
- [ ] "Do you take same-day reservations?"

### 3. Multi-Language Support
Test language switching mid-conversation:

- [ ] **Spanish**: Say "Hola, ¿cuáles son sus horarios?" → AI responds in Spanish
- [ ] **French**: Say "Bonjour, quels sont vos horaires?" → AI responds in French
- [ ] **Language Switch**: Start in English, then switch to Spanish → AI adapts immediately
- [ ] **Non-Latin Scripts** (if testing):
  - [ ] Japanese: "こんにちは" → AI responds in Japanese
  - [ ] Punjabi: "ਸਤ ਸ੍ਰੀ ਅਕਾਲ" → AI responds in Punjabi

### 4. Reservation Booking
- [ ] "I'd like to make a reservation"
- [ ] "Can I book a table for 4 people tomorrow at 7 PM?"
- [ ] AI confirms reservation details

### 5. Call Routing
- [ ] "I need to speak to someone about catering"
- [ ] "Can I talk to someone about a private event?"
- [ ] AI routes appropriately or takes message

### 6. Message Taking
- [ ] "I want to leave a message"
- [ ] "Can you take a message for the manager?"
- [ ] AI collects: name, phone, message

### 7. Voice Quality & Speed
- [ ] AI responses sound natural (fable voice)
- [ ] No choppiness or robotic sounds
- [ ] Responses are brief (1 sentence max)
- [ ] Response time is fast (< 3 seconds after you finish speaking)

### 8. Error Handling
- [ ] If you stay silent → AI prompts you again
- [ ] If you say something unclear → AI asks for clarification
- [ ] If call drops → No errors in logs

---

## 🚨 Critical Issues to Watch For

### Must Fix Before Sales Calls:
1. **Long pause before greeting** - Should be instant
2. **Robotic voice** - Should sound natural (fable voice)
3. **Wrong information** - Hours, specials, etc. must be correct
4. **Language not switching** - AI must respond in caller's language
5. **Call drops or errors** - Must be stable

### Nice to Have (Can Fix Later):
- Response could be slightly faster
- Could handle more complex questions
- Could remember context better

---

## 📞 Sample Test Call Script

**Use this script to test everything quickly:**

```
1. Call the demo number
   → Should hear greeting instantly

2. "What are your hours?"
   → Should get: "Monday-Thursday: 11 AM - 9 PM, Friday-Saturday: 11 AM - 10 PM, Sunday: 12 PM - 8 PM"

3. "Do you have any specials?"
   → Should mention Happy Hour, Weekend Brunch, Family Night

4. "Can I make a reservation for 6 people tomorrow at 7 PM?"
   → Should handle reservation request

5. "Hola, ¿cuáles son sus horarios?"
   → Should respond in Spanish

6. "Thanks, bye!"
   → Should say goodbye and hang up gracefully
```

---

## 🔍 What to Check in Logs

After testing, check your server logs for:

- ✅ No errors or exceptions
- ✅ Language detection working: `🌍 Detected language: Spanish`
- ✅ Language switching: `🌍 Language switched: English -> Spanish`
- ✅ Greeting audio cached: `✅ Greeting audio generated and cached`
- ✅ OpenAI client pre-warmed: `✅ OpenAI client pre-warmed successfully`

---

## ✅ Ready for Sales Call?

Your demo is ready if:
- ✅ All Quick Test items pass
- ✅ FAQ questions answered correctly
- ✅ Multi-language works (at least Spanish)
- ✅ Voice sounds natural and professional
- ✅ No errors in logs

**If all pass → You're ready to demo to clients! 🎉**

