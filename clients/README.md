# Client Configurations

This directory contains configuration files for each client's AI receptionist.

## Directory Structure

```
clients/
├── template/                # Generic template — copy for ANY new business
│   ├── config.json          # Pro plan config (placeholders)
│   └── README.md
├── zenoti-test-store/       # Prototype/test client (925-481-5386)
├── reflectionz-salon/
└── [your-client]/
```

## Adding a New Client

1. Copy the **template** (works for any business type):
   ```bash
   cp -r clients/template clients/[client-slug]
   ```
2. Edit `clients/[client-slug]/config.json` with their info
3. Fill in the onboarding checklist with the client
4. Update `config.json` with their information
5. Deploy their configuration

## Client Configuration Format

Each client has a `config.json` file with:
- Business name, hours, contact info
- Services/menu information
- Specials and promotions
- Reservation/booking rules
- Departments for call routing
- Additional FAQs

## Deployment

Each client can have:
- Their own deployment instance (recommended for production)
- Or use environment variables to switch between clients (for development)



