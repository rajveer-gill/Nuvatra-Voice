# Quick Client Setup Guide

Use this when you get a new client from store-to-store sales.

## ⚡ Fast Setup (30 minutes)

### Step 1: Create Client Folder (2 minutes)

```bash
cd clients
mkdir [business-name]
cd [business-name]
```

Copy template files:
```bash
cp ../reflectionz-salon/config.json .
cp ../reflectionz-salon/onboarding-checklist.md .
```

---

### Step 2: Collect Info (10 minutes)

**Use the onboarding checklist, but here's the minimum:**

1. **Business Name**
2. **Hours** - "Monday-Friday: 9 AM - 5 PM, Saturday: 10 AM - 2 PM"
3. **Address** - Full address
4. **Phone** - Their current number (for forwarding)
5. **Email** - Business email
6. **Services** - List of services or menu link
7. **Specials** - Any current promotions
8. **Booking Rules** - How reservations work
9. **FAQs** - 3-5 common questions

**Quick questions to ask:**
- "What are your hours?"
- "What services do you offer?"
- "Do you have any current specials?"
- "How do reservations work?"
- "What are the most common questions customers ask?"

---

### Step 3: Fill Config File (5 minutes)

Edit `clients/[business-name]/config.json`:

```json
{
  "business_name": "[Business Name]",
  "business_type": "[Restaurant/Salon/etc]",
  "hours": "[Hours from Step 2]",
  "phone": "[Their phone number]",
  "email": "[Their email]",
  "address": "[Their address]",
  "services": [
    "Service 1",
    "Service 2",
    "Service 3"
  ],
  "specials": [
    "Special 1",
    "Special 2"
  ],
  "reservation_rules": [
    "Rule 1",
    "Rule 2"
  ],
  "faqs": [
    {
      "question": "Common question 1",
      "answer": "Answer 1"
    },
    {
      "question": "Common question 2",
      "answer": "Answer 2"
    }
  ]
}
```

---

### Step 4: Set Up Twilio Number (5 minutes)

1. Go to Twilio Console → Phone Numbers → Buy a Number
2. Choose a local number (same area code as business)
3. Configure webhook: `https://your-app-url.com/api/phone/incoming`
4. Save the number

**Or port their existing number:**
- Submit port request in Twilio
- Takes 1-2 business days
- Use temporary number in the meantime

---

### Step 5: Update Backend Config (5 minutes)

**Option A: Environment Variables (Recommended for multi-client)**

Add to your `.env` or Render environment variables:
```
CLIENT_NAME=[business-name]
CLIENT_CONFIG_PATH=clients/[business-name]/config.json
```

**Option B: Update main.py directly (Quick for single client)**

Update `BUSINESS_INFO` in `backend/main.py`:
```python
BUSINESS_INFO = {
    "name": "[Business Name]",
    "hours": "[Hours]",
    # ... etc
}
```

---

### Step 6: Deploy & Test (3 minutes)

1. **Deploy to Render/Railway:**
   ```bash
   git add .
   git commit -m "Add [business-name] client"
   git push
   ```

2. **Test the number:**
   - Call the Twilio number
   - Test: "What are your hours?"
   - Test: "What services do you offer?"
   - Verify answers are correct

3. **Send to client:**
   - "Your AI receptionist is live! Call [number] to test."

---

## 🔧 Advanced Setup (If Needed)

### Integrations

**Zenoti (Salons/Spas):**
- Get API key from client
- Get Center ID
- See `Reflectionz-Salon-AI-Receptionist/ZENOTI-SETUP-GUIDE.md`

**OpenTable (Restaurants):**
- Get API credentials
- Configure reservation booking

**Other:**
- Follow integration-specific guides

---

### Custom Features

**Department Routing:**
- Add departments to config
- Set up forwarding numbers

**SMS Follow-ups:**
- Configure SMS templates
- Set up Twilio SMS

**CRM Integration:**
- Get API credentials
- Configure field mapping

---

## 📋 Pre-Launch Checklist

Before telling client it's ready:

- [ ] Config file is complete
- [ ] Twilio number is configured
- [ ] Webhook is pointing to correct URL
- [ ] Test call works
- [ ] Hours are correct
- [ ] Services are correct
- [ ] FAQs are answered correctly
- [ ] Call forwarding works (if needed)
- [ ] Multi-language works (test Spanish)
- [ ] No errors in logs

---

## 🚀 Go-Live

**Email to client:**

```
Subject: Your AI Receptionist is Live! 🎉

Hi [Name],

Your Nuvatra Voice AI receptionist is now live!

📞 Your number: [Twilio number]
✅ Test it: Call the number and ask "What are your hours?"

What it can do:
- Answer FAQs about hours, services, specials
- Take reservations/bookings
- Forward calls when needed
- Speak any language your customers speak

Next steps:
1. Test the number yourself
2. Share it with your team
3. Update your website/Google listing with the new number (if applicable)

Questions? Just reply to this email!

Best,
[Your Name]
```

---

## 📊 Post-Launch (Week 1)

**Check in after 1 week:**

1. **Review call logs** - Any issues?
2. **Get feedback** - How's it working?
3. **Adjust FAQs** - Add any missing questions
4. **Optimize** - Fine-tune responses

**Questions to ask:**
- "How many calls has it handled?"
- "Any questions it couldn't answer?"
- "Any feedback from customers?"
- "Anything you'd like to change?"

---

## 🆘 Troubleshooting

**"It's not answering"**
- Check Twilio webhook URL
- Verify server is running
- Check logs for errors

**"Wrong information"**
- Update config file
- Redeploy
- Test again

**"Sounds robotic"**
- Verify using fable voice
- Check TTS settings

**"Not understanding customers"**
- Check language detection
- Verify multi-language is enabled
- Test with different languages

---

## 💡 Pro Tips

1. **Start simple** - Get basic info working first, add features later
2. **Test thoroughly** - Don't launch until it's perfect
3. **Get feedback early** - Let client test before going live
4. **Document everything** - Makes future updates easier
5. **Keep it updated** - Update hours, specials, FAQs regularly

---

That's it! You can set up a new client in 30 minutes. 🚀

