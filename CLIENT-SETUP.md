# Client Setup Guide

How to add a new client and what to collect from them.

## What to collect (all plans)

- **Business name**, **address**, **email**
- **Hours of operation** (e.g. "Monday–Friday 9 AM–5 PM, Saturday 10 AM–2 PM")
- **Phone** – number customers call (Twilio) and **call forwarding number** (where to send calls when the AI can’t handle them)
- **Services** – list or menu link
- **Specials / promotions**
- **Reservation or booking rules** – how bookings work, cancellation policy
- **FAQs** – 3–5 common questions and answers

For growth/pro plans: departments, staff, SMS templates, integrations, multi-language as needed. See `clients/reflectionz-salon/onboarding-checklist.md` for a full checklist.

## Add a new client (fast path)

### 1. Create client from template

From the `clients/` directory, copy the **template** (works for any business type — restaurant, salon, retail, etc.):

```bash
cd clients
cp -r template [business-slug]
cd [business-slug]
```

### 2. Edit config

Edit `clients/[business-name]/config.json`: business name, type, hours, phone, email, address, services, specials, reservation_rules, faqs. Use the structure from the template.

### 3. Point the app at this client

- **Multi-client (recommended):** set env vars, e.g. `CLIENT_ID=[business-name]` (backend loads `clients/<CLIENT_ID>/config.json`).
- **Single client:** you can point `main.py` or env at this client’s config.

### 4. Twilio (if using phone)

- Buy/assign a Twilio number; set **A CALL COMES IN** and **CALL STATUS** webhooks to your backend URL (e.g. `https://your-app.railway.app/api/phone/incoming` and `.../api/phone/status`). See [PHONE-SETUP.md](./PHONE-SETUP.md).

### 5. Deploy and test

Deploy backend (and frontend if needed). Call the number and test hours, services, and a booking. Adjust config and redeploy as needed.

## Client config structure

See [clients/README.md](./clients/README.md) for config fields and options. Each client lives under `clients/<client-id>/` with a `config.json` (and optional README or checklist).
