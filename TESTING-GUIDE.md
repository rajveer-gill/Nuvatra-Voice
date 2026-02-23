# Testing Your AI Receptionist

## Web (browser)

1. Start the app: `npm run dev` or `./bin/dev` / `bin\dev.cmd`
2. Open **http://localhost:3000**
3. Click **Voice Call** → **Start Call**
4. Say e.g. "What are your hours?", "I need to schedule an appointment" – the AI should respond with voice.
5. Use the **Appointments** tab to create or accept/reject appointments; use **Dashboard** for stats and call info.

## Phone (Twilio)

1. Ensure backend is deployed and Twilio webhooks point to your backend URL (see [PHONE-SETUP.md](./PHONE-SETUP.md)).
2. Call your Twilio number. You should hear the AI greeting.
3. Try: "What are your hours?", "I'd like to book an appointment", "Can you help me?"
4. Check backend/hosting logs for requests and errors.

## Troubleshooting

- **No answer / no audio:** Check Twilio webhooks (A CALL COMES IN → `https://your-backend-url/api/phone/incoming`, CALL STATUS → `.../api/phone/status`). Verify env vars (OPENAI_API_KEY, TWILIO_*, NGROK_URL or deployment URL). Check hosting logs.
- **Wrong or missing info:** Update client config and redeploy.
- **Web stuck on "Starting...":** Stop dev server, delete `.next`, run `npm run dev` again. See [QUICK-START.md](./QUICK-START.md).
