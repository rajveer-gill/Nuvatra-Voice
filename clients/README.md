# Client Configurations

This directory contains configuration files for each client's AI receptionist.

## Directory Structure

```
clients/
├── reflectionz-salon/
│   ├── config.json          # Client business configuration
│   ├── README.md            # Client-specific setup info
│   └── onboarding-checklist.md  # Checklist for collecting client info
└── [future-client]/
    └── ...
```

## Adding a New Client

1. Create a new directory: `clients/[client-name]/`
2. Copy the template files from `reflectionz-salon/`
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



