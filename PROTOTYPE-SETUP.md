# Prototype setup – 925-481-5386

This project uses **+1 (925) 481-5386** as the **test/prototype** Twilio number. The template for new businesses is **Zenoti Test Store** (`clients/zenoti-test-store`), with Pro features (appointments, staff, SMS accept/reject, slot memory, analytics).

---

## What you need to provide

### 1. Backend environment (already partly done)

In **`backend/.env`** we need:

| Variable | Purpose | You have? |
|----------|---------|-----------|
| `OPENAI_API_KEY` | AI and TTS | ✓ (you’re running the app) |
| `TWILIO_ACCOUNT_SID` | Twilio account | From Twilio Console → Account |
| `TWILIO_AUTH_TOKEN` | Twilio auth | From Twilio Console → Auth Token |
| `TWILIO_PHONE_NUMBER` | **+19254815386** (this number) | ✓ Set for prototype |
| `TWILIO_SMS_FROM` | Optional; defaults to `TWILIO_PHONE_NUMBER` | Only if you use a different number for SMS |
| `CLIENT_ID` | **zenoti-test-store** to use the Pro template | Optional; set for template |

If 925-481-5386 can send SMS, leave `TWILIO_SMS_FROM` unset (we’ll use the same number). If not, set `TWILIO_SMS_FROM` to an SMS-capable Twilio number.

---

### 2. Twilio webhooks (so the number answers and logs calls)

In **Twilio Console** → **Phone Numbers** → **Manage** → **Active Numbers** → select **+1 925 481 5386**:

- **Voice – A CALL COMES IN:**  
  `https://YOUR_BACKEND_URL/api/phone/incoming`  
  Method: **POST**

- **Voice – CALL STATUS CHANGES:**  
  `https://YOUR_BACKEND_URL/api/phone/status`  
  Method: **POST**

**YOUR_BACKEND_URL**:

- **Local testing:** run `ngrok http 8000`, then use the ngrok URL (e.g. `https://abc123.ngrok.io`).
- **Deployed (e.g. Railway):** use your app URL (e.g. `https://your-app.railway.app`).

After you change webhooks, save the number in Twilio.

---

### 3. SMS (accept/reject and confirmations)

- The app sends SMS for: appointment **accepted** (confirmation) and **rejected** (suggest other times).
- **No extra “text auth”** is required for this; we use Twilio’s API with your Account SID and Auth Token.
- If 925-481-5386 is **SMS-capable**, nothing else is needed.
- If it’s **voice-only**, set `TWILIO_SMS_FROM` in `backend/.env` to another Twilio number that can send SMS.

---

### 4. Optional: call forwarding

- To send live calls to a real person when the AI can’t help, set **`forwarding_phone`** in the client config (or `BUSINESS_FORWARDING_PHONE` in `.env`) to an E.164 number (e.g. your cell).
- For the prototype template this is optional.

---

## Quick checklist

- [ ] **backend/.env**: `OPENAI_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER=+19254815386`
- [ ] **Twilio**: 925-481-5386 Voice URL → `https://YOUR_BACKEND_URL/api/phone/incoming`, Status → `.../api/phone/status`
- [ ] **Backend reachable**: local = ngrok; or deploy and use that URL in webhooks
- [ ] **SMS**: Same number works for SMS, or set `TWILIO_SMS_FROM` to an SMS-capable number
- [ ] **Template**: Set `CLIENT_ID=zenoti-test-store` to use the Pro template with this number

Once this is done, calls to **925-481-5386** will hit your backend and use the Zenoti Test Store (Pro) template.
