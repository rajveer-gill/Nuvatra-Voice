# Client Configurations

Configuration files for each client's AI receptionist.

## Directory Structure

```
clients/
├── template/                # Generic template — copy for any new business
│   ├── config.json          # Pro plan config (placeholders)
│   └── README.md
├── zenoti-test-store/       # Test client
├── reflectionz-salon/
└── [your-client]/
```

## Adding a New Client

1. **Copy the template**
   ```bash
   cp -r clients/template clients/[business-slug]
   ```

2. **Edit** `clients/[business-slug]/config.json`: business name, hours, phone, email, address, services, specials, reservation_rules, departments, staff, forwarding_phone. Use the template structure.

3. **Point the app** at this client: set `CLIENT_ID=[business-slug]` (backend loads `clients/<CLIENT_ID>/config.json`). For multi-tenant, create the tenant via `/admin` and assign a Twilio number.

4. **Twilio:** Set the number’s Voice webhook to `https://your-backend-url/api/phone/incoming` and Status to `.../api/phone/status`. See [PHONE-SETUP.md](../PHONE-SETUP.md). For invite-only flow see [INVITE-ONLY-SETUP.md](../INVITE-ONLY-SETUP.md).

5. **Deploy and test** – call the number and verify hours, services, and booking.

## What to Collect From the Client

- Business name, address, email, hours
- Phone (Twilio) and call forwarding number
- Services (list or menu link), specials, reservation/booking rules
- A few FAQs. For growth/pro: departments, staff, SMS preferences.

See `reflectionz-salon/onboarding-checklist.md` for a detailed checklist.

## Config Format

Each client has `config.json` with: business name, hours, contact info, services, specials, reservation_rules, departments (routing), optional staff and locations.



