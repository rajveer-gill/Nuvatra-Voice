# Example Salon - AI Receptionist Configuration

## Client Information

**Business Name:** Example Salon  
**Industry:** Salon / Beauty Services  
**Status:** Template for new salon clients

## Configuration Status

- [ ] Hours of operation collected
- [ ] Menu link / services list collected
- [ ] Specials collected
- [ ] Reservation or booking rules collected
- [ ] Business phone number collected (for call forwarding)
- [ ] Business email collected
- [ ] Business address collected
- [ ] Business Number collected
- [ ] Critical FAQs collected

## Setup Instructions

1. Fill in all the information in `config.json`
2. Update backend to load this client's configuration (or create tenant via admin with this client_id)
3. Deploy with client-specific environment variables
4. Configure Twilio webhook to point to this client's deployment
5. Test the phone number

## Deployment

Once configuration is complete:
- Deploy to: [Render/Railway URL]
- Twilio Number: [To be assigned]
- Webhook URL: [To be configured]

## Notes

Add any client-specific notes or requirements here.
