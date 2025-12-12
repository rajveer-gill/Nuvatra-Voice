# Client Onboarding Information Requirements

This document outlines all information needed from clients based on their selected plan tier.

---

## 🟦 STARTER PLAN ($149/mo) - Required Information

**Core Business Information:**
1. ✅ **Business Name** - Full legal or operating name
2. ✅ **Business Phone Number** - The number customers call (Twilio number)
3. ✅ **Call Forwarding Number** - Where to forward calls when AI can't handle (voicemail or human)
4. ✅ **Business Email** - For notifications and contact
5. ✅ **Business Address** - Full street address
6. ✅ **Hours of Operation** - Detailed hours (e.g., "Monday-Friday: 9 AM - 5 PM, Saturday: 10 AM - 2 PM")
7. ✅ **Menu Link / Services List** - URL or list of services/products offered
8. ✅ **Specials / Promotions** - Current specials, deals, or promotions
9. ✅ **Reservation or Booking Rules** - How reservations work, cancellation policy, party size limits, etc.
10. ✅ **Critical FAQs** - Common questions and answers specific to their business

**Clarification Needed:**
- Is "Business Number" the same as "Call Forwarding Number"?
  - If different: Which is the Twilio number (incoming) vs forwarding destination (outgoing)?

---

## 🟧 GROWTH PLAN ($249/mo) - Additional Information

**Everything in Starter Plan +:**

11. **Department Routing** (if applicable)
    - Department names (e.g., "Sales", "Support", "Billing")
    - Department phone numbers or extensions for forwarding
    - Department descriptions (what each handles)

12. **Custom AI Voice Preferences** (optional)
    - Voice selection (fable, nova, alloy, echo, onyx, shimmer)
    - Tone preferences (peppy, professional, warm, etc.)

13. **SMS Follow-up Templates** (if using SMS automation)
    - Welcome message template
    - Menu/services follow-up message
    - Appointment reminder template
    - Custom SMS content

14. **Lead Capture Fields** (if using lead capture)
    - Required fields: Name, Phone, Reason for calling
    - Optional fields: Email, Preferred contact method, etc.

15. **CRM / Google Sheets Integration** (if using)
    - CRM type (HubSpot, Salesforce, etc.) or Google Sheets URL
    - API credentials/keys
    - Field mapping preferences

16. **Multi-language Support** (if needed)
    - Primary languages to support (English + Spanish, etc.)
    - Note: System auto-detects, but good to know primary languages

---

## 🟥 PRO PLAN ($399/mo) - Additional Information

**Everything in Growth Plan +:**

17. **Multi-Location Data** (if multi-location business)
    - For each location:
      - Location name
      - Address
      - Phone number
      - Hours of operation (if different per location)
      - Services offered at that location

18. **Staff Call Forwarding** (if using staff routing)
    - For each staff member:
      - Name
      - Role/Department
      - Phone number
      - Availability (hours/days available)
      - What they handle

19. **Advanced Workflow Configuration**
    - **Pickup Orders**: Process, payment, timing
    - **Class Scheduling**: Class types, capacity, booking rules
    - **Staff Routing**: Who handles what, escalation rules
    - **Contractor Quotes**: Quote process, follow-up procedures

20. **Custom Routing Trees** (if using custom routing)
    - Call flow logic
    - Decision points
    - Escalation paths

21. **Analytics Preferences** (optional)
    - What metrics they want to track
    - Reporting frequency

---

## 📋 Quick Reference Checklist

### For ALL Plans:
- [ ] Business Name
- [ ] Business Phone Number (Twilio/incoming)
- [ ] Call Forwarding Number (where calls go when AI can't handle)
- [ ] Business Email
- [ ] Business Address
- [ ] Hours of Operation
- [ ] Menu Link / Services List
- [ ] Specials / Promotions
- [ ] Reservation/Booking Rules
- [ ] Critical FAQs

### For GROWTH Plan:
- [ ] Departments (if applicable)
- [ ] SMS Templates (if using SMS)
- [ ] Lead Capture Preferences
- [ ] CRM/Integration Credentials (if using)

### For PRO Plan:
- [ ] Multi-Location Data (if applicable)
- [ ] Staff Contact Info (if using staff routing)
- [ ] Advanced Workflow Details
- [ ] Custom Routing Logic (if applicable)

---

## 🔍 Important Clarifications Needed

1. **Phone Number Confusion:**
   - Clarify: "Business Number" vs "Call Forwarding Number"
   - One is the Twilio number (incoming calls)
   - One is where to forward (outgoing/human)

2. **Call Forwarding Behavior:**
   - When should calls be forwarded? (Always, only when AI can't handle, urgent only?)
   - Forward to voicemail or live person?
   - What's the escalation process?

3. **Reservation System:**
   - Do they use a platform? (OpenTable, Resy, etc.)
   - Or manual booking only?
   - This affects how reservations are processed

---

## 💡 Recommendations

1. **Create a Form/Onboarding Flow** organized by plan tier
2. **Make it Progressive** - Show only fields relevant to their selected plan
3. **Add Validation** - Ensure required fields are filled before activation
4. **Store in Database** - Don't hardcode in config files for multi-client setup
5. **Allow Updates** - Let clients update their info after onboarding




