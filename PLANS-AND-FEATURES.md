# Plans & Feature Matrix

The **template** (`clients/template`) is the **Pro plan** — highest tier. This doc maps your plan features to what’s implemented today.

---

## Plan tiers (summary)

| Tier   | Price  | Template / use |
|--------|--------|----------------|
| Starter | $149/mo | Reduced config (single location, no staff routing, no SMS automation) |
| Growth | $249/mo | Add voice/tone, SMS automation, lead capture, multi-language, departments |
| **Pro** | **$399/mo** | **Full template: multi-location, staff forwarding, customer memory, analytics, custom workflows** |

---

## Call handling

| Feature | Starter | Growth | Pro | Implemented? |
|--------|---------|--------|-----|--------------|
| Answers inbound calls instantly | ✔ | ✔ | ✔ | **Yes** (Twilio) |
| 24/7 call coverage | ✔ | ✔ | ✔ | **Yes** |
| Handles overflow and after-hours | ✔ | ✔ | ✔ | **Yes** (AI always answers) |
| Conversational voice (not IVR menus) | ✔ | ✔ | ✔ | **Yes** (GPT + TTS) |
| Understands caller intent | ✔ | ✔ | ✔ | **Yes** |
| Captures caller details | ✔ | ✔ | ✔ | **Yes** (name, phone, reason in flow) |
| Handles FAQs automatically | ✔ | ✔ | ✔ | **Yes** (from config) |
| Business info (hours, services, location, pricing) | ✔ | ✔ | ✔ | **Yes** (config) |
| Reservations and bookings | ✔ | ✔ | ✔ | **Yes** (with slot memory) |
| Appointment scheduling | ✔ | ✔ | ✔ | **Yes** |
| Basic orders (where applicable) | — | — | Optional | **Partial** (conversational; no POS) |
| Routes calls to staff | — | ✔ | ✔ | **Yes** (Pro: by name) |
| Department routing | — | ✔ | ✔ | **Yes** (config: departments) |
| Multi-location routing | — | — | ✔ | **Yes** (config: locations) |

---

## Follow-up & messaging

| Feature | Starter | Growth | Pro | Implemented? |
|--------|---------|--------|-----|--------------|
| SMS missed-call follow-ups | ✔ (text reply) | ✔ | ✔ | **Roadmap** (manual today) |
| Automated text responses | — | ✔ | ✔ | **Partial** (accept/reject SMS only) |
| Appointment reminders | ✔ (basic) | ✔ | ✔ | **Roadmap** (no cron/scheduler yet) |
| Booking confirmations | — | ✔ | ✔ | **Yes** (SMS on accept) |
| Lead capture messages | — | ✔ | ✔ | **Partial** (captured in call; no auto-SMS) |
| Post-call summaries | — | — | ✔ | **Roadmap** (call log has outcome, not full summary) |

---

## Smart features

| Feature | Starter | Growth | Pro | Implemented? |
|--------|---------|--------|-----|--------------|
| Recognizes repeat callers | — | — | ✔ | **Yes** (caller_memory) |
| Customer memory context | — | — | ✔ | **Yes** |
| Custom workflows (booking, quotes, scheduling) | — | ✔ | ✔ | **Yes** (booking flow; quotes/scheduling in prompt) |
| Business-specific conversation tuning | ✔ | ✔ | ✔ | **Yes** (config) |
| Natural conversational tone | ✔ | ✔ | ✔ | **Yes** |

---

## Language & voice

| Feature | Starter | Growth | Pro | Implemented? |
|--------|---------|--------|-----|--------------|
| Multi-language support | ✘ | ✔ | ✔ | **Yes** (detect + respond) |
| Custom AI voice options | ✘ | ✔ | ✔ | **Yes** (alloy, echo, fable, onyx, nova, shimmer) |
| Voice tone tuning | ✘ | ✔ | ✔ | **Partial** (prompt tuning) |
| Voice clone add-on | — | — | Optional | **No** (roadmap) |

---

## Data & reporting

| Feature | Starter | Growth | Pro | Implemented? |
|--------|---------|--------|-----|--------------|
| Call transcripts | ✔ | ✔ | ✔ | **Partial** (Whisper for recordings; not full per-call transcript in UI) |
| Call summaries | ✔ | ✔ | ✔ | **Partial** (outcome + duration in log) |
| Lead capture records | — | ✔ | ✔ | **Yes** (messages + appointments) |
| CRM integration | ✘ | ✔ | ✔ | **Roadmap** |
| Google Sheets integration | ✘ | ✔ | ✔ | **Roadmap** |
| Call analytics (higher tiers) | — | — | ✔ | **Yes** (by outcome, hour, day; dashboard) |
| Missed-call recovery tracking | — | — | ✔ | **Yes** (outcome: missed) |

---

## Template = Pro

The **template** (`clients/template`) includes every **Pro** option the app supports today:

- **Config:** `plan: "pro"`, departments, staff (with forwarding), locations, services, reservation_rules, greeting.
- **Behavior:** 24/7 answering, FAQs, bookings with slot memory, staff/department/location routing, customer memory, call logging, analytics, accept/reject with SMS, multi-language, custom voice (configurable).

For **Starter** or **Growth** clients you can copy the template and strip or simplify (e.g. single location, no staff routing, no SMS) per your tier rules.
