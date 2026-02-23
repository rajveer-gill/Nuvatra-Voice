# Zenoti Test Store (Pro Plan)

Test location for Nuvatra Voice — no Zenoti API integration. Full Pro features: staff forwarding, customer memory, call logging, analytics.

## Setup

1. Fill in `config.json`:
   - `forwarding_phone`: main store number (E.164, e.g. +15551234567)
   - `phone`, `email`, `address`
   - For each entry in `staff`, set `phone` (E.164)
   - For each entry in `locations`, set `forwarding_phone` and `address` if needed

2. Set environment for this client:
   - `CLIENT_ID=zenoti-test-store`
   - For accept/reject SMS: use `TWILIO_PHONE_NUMBER` for SMS if it supports SMS, or set `TWILIO_SMS_FROM` to an SMS-capable number (E.164).

3. Twilio: set your number’s **Voice URL** to `https://your-backend-url/api/phone/incoming` and **Status Callback URL** to `https://your-backend-url/api/phone/status` (so call end and duration are logged for analytics).

## Pro Features Enabled

- 24/7 call answering
- Staff call forwarding (transfer to Manager or Reception by name)
- Customer memory (repeat caller recognition)
- Call logging and analytics (peak times, outcomes, recent calls)
- Reservations and messages (stored in dashboard; no Zenoti sync)
- Appointment review for Zenoti: copy-paste block, Accept (sends confirmation SMS), Reject (releases slot and sends "when else available?" SMS)
- Slot memory so the AI does not double-book; suggests another time or stylist if slot is taken
- Multi-language support
- Custom greeting and business info

## Data Files (auto-created)

- `call_log.json` — call history for analytics
- `caller_memory.json` — repeat caller info for personalization
- `booked_slots.json` — reserved date/time slots (avoids double-book; used by AI)
