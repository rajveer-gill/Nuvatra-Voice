# Nuvatra Voice — Inbound call flow (v1)

This document is the product-facing specification for how an inbound call should behave. Implementation aligns with the receptionist system prompt (`backend/prompts/receptionist.py`) and Twilio voice/SMS handlers in the FastAPI app.

## Scope

- **Inbound PSTN/voice** to a tenant’s business number.
- **Transactional SMS** after the call or as part of ongoing appointment flows (not bulk marketing).
- **Compliance**: disclosures and STOP/HELP behavior must stay consistent with [Privacy Policy](https://nuvatrahq.com/privacy), [Terms of Service](https://nuvatrahq.com/terms), and the public [SMS consent](/sms-consent) page.

## High-level states

| State | Goal |
|--------|------|
| **Answer** | Call is answered immediately (no dead air). |
| **Greeting_Disclosure** | Branded greeting; if SMS or recording may apply, brief disclosure (see below). |
| **IntentCapture** | Understand caller goal: book, reschedule, cancel, question/FAQ, urgent, speak to a person. |
| **BookingFlow** | Service → live availability → slot offer → collect details → verbal confirmation. |
| **ConfirmVerbal** | Caller confirms date/time/service on the call before committing. |
| **Emit_BOOKING** | AI emits machine-parseable `BOOKING:` line when requirements met (see prompt rules). |
| **PostCallSMS** | Optional transactional SMS (confirmation/reminder); subject to opt-out and plan limits. |
| **HumanEscalation** | Transfer or callback when AI cannot complete safely or caller insists. |

```text
InboundCall → Greeting_Disclosure → IntentCapture
     → BookingFlow → ConfirmVerbal → Emit_BOOKING → PostCallSMS (optional)
IntentCapture → HumanEscalation (urgent / staff request)
PostCallSMS channel → STOP → SMS_opt_out_only (voice booking may continue)
```

## Name capture policy

Unique or noisy names are expected. Do **not** rely on a single speech-to-text pass.

1. **Ask** for name naturally.
2. **Read back** what was understood.
3. **Confirm** (“Is that right?”).
4. If uncertain or caller corrects: ask to **spell** first name, then last if needed (letter-by-letter acceptable).
5. **Anchor identity on phone number** from the carrier where possible; name supplements the record.

## Phone number policy (voice)

The caller’s phone is available from the telephony layer for outbound SMS and booking linkage. The receptionist must **not** ask “what’s your number?” for a normal inbound call unless the product explicitly supports masked/anonymous caller-ID flows.

## SMS channel policy vs voice

- **Transactional SMS** (appointments, replies tied to service): aligned with the caller’s interaction with the business.
- **STOP** (and CTIA-style synonyms): opts the handset out of **SMS from that business number** for that tenant. Further promotional or conversational SMS must not be sent until **START** (or equivalent resubscribe flow).
- **STOP does not cancel a voice booking in progress.** The caller may complete booking **on the call**, call back, or use another channel you offer (e.g. web). SMS confirmation text may include “To complete booking, call …” when appropriate.
- **HELP**: automated help/info reply with contact path.

Implementation reference: SMS compliance keywords and opt-out storage are handled in the SMS webhook path; voice continues independently.

## Disclosure text (reference)

Short-form clauses used in greetings or first SMS should be consistent with legal pages:

- Message & data rates may apply.
- Message frequency varies based on interactions with the service.
- Reply **STOP** to opt out, **HELP** for help.

Recording (when enabled): spoken disclosure that the call may be recorded for quality and training (see `CALL_RECORDING_ENABLED`).

## Implementation touchpoints (code map)

| Concern | Location |
|---------|----------|
| System prompt (behavior, `BOOKING:` format, slots, 12h time) | `backend/prompts/receptionist.py` — `get_system_prompt` |
| Greeting / recording disclosure audio | `get_greeting_text()` and TTS paths in app voice handlers (`main.py` / routers) |
| Slot availability text fed into prompt | `get_booked_slots_prompt_text` (booking module — imported into prompt builder) |
| Twilio voice webhook | Voice router (`/api/phone/*`) |
| Twilio SMS webhook / STOP START HELP | SMS router (`/api/sms/incoming`) |
| Tenant DB, appointments, opt-out | `database.py` |

## Change control

Changes to caller-visible behavior should update:

1. This document (intent/states).
2. `backend/prompts/receptionist.py` (what the model is instructed to do).
3. Pytest tests that lock critical rules (booking token format, slot constraints, time format).
