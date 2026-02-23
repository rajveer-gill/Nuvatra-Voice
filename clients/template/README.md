# Business Template — Pro Plan ($399/mo)

**Generic template for any new business** (restaurant, salon, retail, professional services). This is the **highest tier**: copy this folder when onboarding a Pro client. For Starter or Growth, use the same config and simplify (e.g. single location, no staff routing) per tier.

---

## Pro features included (template supports all of these)

**Call handling**  
Answers calls instantly, 24/7 • Conversational voice (not IVR) • Understands intent • Captures caller details • FAQs, hours, services, location, pricing • Reservations & appointment scheduling • Staff call forwarding (by name) • Department routing • Multi-location routing

**Follow-up & messaging**  
Booking confirmations (SMS on accept) • Reject SMS (“when else available?”) • Lead capture in conversation (stored in messages/appointments)

**Smart**  
Repeat caller recognition • Customer memory • Custom booking/scheduling flow • Business-specific tuning • Natural tone

**Language & voice**  
Multi-language • Custom AI voice (alloy, echo, fable, onyx, nova, shimmer)

**Data & reporting**  
Call log • Analytics (by outcome, hour, day) • Lead capture records • Missed-call outcome tracking

See **[PLANS-AND-FEATURES.md](../../PLANS-AND-FEATURES.md)** in the repo root for the full feature matrix and what’s implemented vs roadmap.

---

## Apply template to a new business

1. Copy the template:
   ```bash
   cp -r clients/template clients/[business-slug]
   ```

2. Edit `clients/[business-slug]/config.json`:
   - `business_name`, `hours`, `phone`, `email`, `address`
   - `services` (menu items, treatments, etc.)
   - `specials`, `reservation_rules`, `departments`
   - `staff` (names, roles, phone numbers for forwarding)
   - `locations` (for multi-location)
   - `forwarding_phone` (where to send calls when AI can’t handle)

3. Set `CLIENT_ID=[business-slug]` and deploy.
