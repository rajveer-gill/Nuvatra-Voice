# Booking-service extraction — plan & state

Splitting the booking domain out of `main.py` into `booking_service.py`, strangler-fig
style (same discipline as `config_service`/`sms_service`/`clerk_service`).

## Done
- [x] **Cut 1 — stateless primitives** (commit `84aff03`). 13 pure helpers + the
  `DEFAULT_SLOT_DURATION_MINUTES` constant. No runtime/DB/cache state; deps = config_service
  + stdlib only. config_service calls are module-qualified (the patch target); re-exported
  from main. Two monkeypatches retargeted (`main.get_business_info` → `config_service.get_business_info`).
  Full unit suite green (380 passed / 10 skipped).

- [x] **Cut 2 — stateful slot/calendar engine** (this commit). 21 functions + 3 module vars
  (`_CALENDAR_HOLDING_STATUSES`, `_booked_slots_cache`, `_BOOKED_SLOTS_CACHE_TTL_SEC`). Bodies
  qualified to `runtime.appointments`, `database.db_*`/`database._client_id`, `config_service.*`;
  `observability.system_debug/info` imported by name. Re-exported from main so the staying
  booking-creation/voice/SMS callers resolve. Retargeted patches in test_booked_slots_prompt
  (`_get_all_booked_slots_merged`, `datetime`, `get_db_client_id`→`database._client_id`,
  `get_business_info`→`config_service`) and test_slot_calendar_filter (`_load_booked_slots`,
  `db_appointments_get_all`→`database`). test_appointment_cancel patches stay on `main` (the
  cancel route is main-resident, so the re-export rebind reaches it). Verified BOTH gates:
  unit 380 passed / 10 skipped; **DB-integration 384 passed / 1 xfailed** (real Postgres,
  exercises `db_booked_slots_*`). Route set unchanged (82). main.py 8562 -> 8084.

## (historical) Cut 2 plan — the stateful slot/calendar engine

### Set to MOVE (closed; verify with the AST script in /tmp/extract_booking.py, just swap the name list)
State + const: `_booked_slots_cache` (module dict), `_invalidate_booked_slots_cache`,
`_CALENDAR_HOLDING_STATUSES`.
Pure slot mechanics (deferred from cut 1): `_slot_overlaps`, `_staff_slot_key`, `_staff_label_for_slot_key`.
Persistence: `_load_booked_slots`, `_save_booked_slots`.
Merge/calendar: `_appointment_rows_for_calendar_merge`, `_appointment_by_id_map`,
`_booked_slot_rows_that_hold_calendar`, `_get_all_booked_slots_merged`,
`_booked_slot_duration_by_appointment_id`.
Availability: `_slot_blocking_details`, `is_slot_available`, `reserve_slot`, `release_slot`.
Reconcile: `_reconcile_sms_appointment_slot_after_detail_change`, `_reconcile_booked_slots_orphans`,
`_voice_calendar_holds`.
Public: `get_booked_slots`, `get_booked_slots_prompt_text`.
Tenant: `_tenant_sms_from_number`.

### STAYS in main (do NOT move — interleaved in the same line region, voice/SMS-adjacent)
`_phones_match_for_booking` (uses main-local `normalize_phone`), `_supersede_pending_customer_drafts_for_slot`
(called only by `_create_appointment_from_booking`), `_create_appointment_from_booking`,
`_voice_booking_nudge_message`, `_should_attempt_voice_booking_extraction`,
`_extract_booking_line_from_conversation` (real-time GPT call), `_strip_booking_directive_for_voice`,
`parse_booking`, `_prepare_parsed_booking`, `_apply_booking_customer_name`, `_staff_name_set`,
`_caller_memory_name_usable`, `_validate_booking_requirements`, `_normalize_service_*`-conversation
helpers, `_notify_staff_pending_review`, `_maybe_handle_staff_sms_approval`,
`_staff_pending_review_sms_enabled`, `staff_roster_ready_for_booking`, and the
`_suggests_booking`/`_conversation_*`/`_count_booking_user_turns`/`_caller_indicated_*`/`_staff_choice_required`
detection helpers (these go with the conversation/voice domain later).

### Body edits required after AST move (the engine is NOT edit-free like cut 1)
- `appointments` (in-mem list) → `runtime.appointments` (in `_appointment_rows_for_calendar_merge`).
- bare `db_*(` → `database.db_*(` — `import database`. (db funcs used: `db_booked_slots_load`,
  `db_booked_slots_save`, `db_appointments_get_all`, plus whatever `_tenant_sms_from_number` uses
  e.g. `db_tenant_get_by_client_id`.)
- `get_client_data_dir(` → `config_service.get_client_data_dir(`.
- `get_business_info(` → `config_service.get_business_info(`.
- `get_booked_slots_prompt_text` likely needs `booking_fields` imports (`booking_context_from_business`)
  and per-stylist helpers — read its full body (~line 2487+) and confirm closure before moving.
- `_tenant_sms_from_number` (def ~1456) — read body; confirm it doesn't call `normalize_phone`
  (if it does, that's a blocker → either keep it in main or move `normalize_phone` to sms_service first).

### Test retargets (patches of moved functions → `booking_service.*`)
- `test_slot_calendar_filter.py`: `patch("main._load_booked_slots")` → `booking_service._load_booked_slots`.
- `test_booked_slots_prompt.py`: `patch("main._get_all_booked_slots_merged")`,
  `main._invalidate_booked_slots_cache`, `main.get_booked_slots_prompt_text` → `booking_service.*`.
- `test_appointment_cancel.py`: `monkeypatch.setattr(main, "_tenant_sms_from_number", ...)` → `booking_service`.
- Any test patching `main.get_business_info`/`main.get_client_data_dir` that exercises a MOVED engine
  function → retarget to `config_service.*` (the owning module). The unit-suite run surfaces these.

### Verification gate (BOTH, not just unit)
1. Import smoke + identity (`main.X is booking_service.X`).
2. OpenAPI route set unchanged (82 HTTP routes).
3. Unit suite: `python3.9 -m pytest -q` → 380 passed / 10 skipped.
4. **DB-integration** (the slot persistence path only runs under USE_DB):
   `DATABASE_URL=postgresql://postgres:dev@localhost:5432/postgres python3.9 -m pytest -q`
   → 384 passed (container `csurge-pg`, see DB-CONCURRENCY.md runbook). This is the cut that
   actually exercises `db_booked_slots_*` — do not skip it.

### Why a separate cut
The engine is the slot-reservation path (double-booking = unforgivable). It needs invasive body
qualification + mutable cache handling + the DB-integration run — a heavier, riskier loop than the
pure-primitive cut. Worth its own focused pass.
