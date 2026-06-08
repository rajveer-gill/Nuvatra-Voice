# Background bulk onboarding pipeline — design & build plan

**Goal:** reliably onboard 60+ stores at once, with Twilio number auto-purchase.
Replaces the synchronous `admin_bulk_create_tenants` (which times out and leaves
half-provisioned tenants on partial failure — see the findings that motivated this).

**Decisions locked in:** Twilio numbers are **auto-purchased in code**
(`twilio_provision.purchase_number`, already built + tested). Onboarding runs as a
**background job**, not a synchronous request.

## Shape

Submit → return job id immediately → process tenants async with **per-tenant,
idempotent, resumable** steps and a **status row per tenant**. Partial failure is
recoverable per-tenant (re-run pending/failed), never all-or-nothing.

```
POST /api/admin/provisioning/jobs        -> {job_id}           (validates, persists tasks, kicks worker)
GET  /api/admin/provisioning/jobs/{id}   -> {status, counts, tasks[]}
POST /api/admin/provisioning/jobs/{id}/resume -> re-run pending+failed tasks
```

## Per-tenant idempotent step machine (`provision_one_tenant`)

Each step checks `steps_done` and skips if present, so a retry resumes:

1. **tenant_created** — `database.db_tenant_create(...)` (already `ON CONFLICT (client_id) DO NOTHING` = idempotent); fetch id.
2. **number_purchased** — skip if tenant already has a number; else
   `twilio_provision.purchase_number(area_code=task.area_code or default)`, store
   `phone_e164`, assign to tenant. (purchase_number sets webhooks at creation.)
3. **config_seeded** — `config_service._default_client_config_data` + `save_raw_client_config` (upsert = idempotent).
4. **clerk_invited** — invite/link the owner email (idempotent upsert).

Any step error → task `status=failed`, `error` recorded, **other tenants continue**.

## Build order (each its own green commit)

1. ✅ `twilio_provision.purchase_number` + tests — **done** (commit 0bc9f95).
2. **Extract Clerk linking out of main** — `_clerk_link_email_to_tenant` and the
   `_clerk_*` helpers it needs currently live in main.py; a service can't import main.
   Move them to a `clerk_service.py`, re-export from main (same discipline as
   sms_service/config_service). **Prerequisite for step 4 of the machine.**

   The cluster is `main.py` ~4078–4420 (10 functions: `_clerk_api_json_list`,
   `_clerk_revoke_active_sessions`, `_clerk_user_ids_from_api`,
   `_clerk_user_ids_from_tenant_members`, `_clerk_user_ids_for_email`,
   `_clerk_relink_users_to_tenant`, `_clerk_invite_error_message`,
   `_clerk_clear_tenant_access`, `_clerk_relink_user_to_tenant`,
   `_clerk_link_email_to_tenant`). Module-qualify on extraction:
   - `_clerk_fetch_user_link`, `_clerk_patch_user_tenant_metadata` → `deps.*` (already moved there in 1b)
   - `db_tenant_*` (invite_upsert/delete, member_assign_owner, all_member_clerk_ids) → `database.*`
   - `runtime.USE_DB`
   **Gotcha — also-needed main helpers** (the tail of `_clerk_link_email_to_tenant`):
   `_admin_access_log`, `_admin_access_debug_enabled`, `_admin_tenant_access_debug_snapshot`.
   Cleanest handling: move `_admin_access_debug_enabled` (tiny env flag) to `deps`
   alongside `_settings_load_debug_enabled`; move `_admin_access_log` to `deps`/observability;
   and either move `_admin_tenant_access_debug_snapshot` too or have the admin *route*
   (not the service) attach the debug snapshot. Tests to retarget:
   `test_clerk_link_multiple_users` patches `main._clerk_user_ids_for_email` /
   `main._clerk_relink_user_to_tenant` → repoint to `clerk_service.*`.
3. **DB schema + persistence** in database.py: `provisioning_jobs` (id, created_by,
   total, status, timestamps) and `provisioning_tasks` (id, job_id, client_id, name,
   email, area_code, plan, status, phone_e164, steps_done JSONB, error, attempts,
   timestamps). Add `db_provisioning_*` CRUD + a summary query. Tests via mocked cursor.
4. **`provisioning.py`** — `provision_one_tenant(task, *, base_url, account_sid,
   auth_token, default_area_code)` implementing the step machine, calling
   `database.*`, `twilio_provision.purchase_number`, `config_service.*`,
   `clerk_service.*` (all module-qualified). Unit tests mock those deps and assert
   idempotency (re-run skips completed steps) + per-step failure recording.
5. **`run_provisioning_job(job_id)`** — load pending/failed tasks, process with
   **bounded concurrency** (`asyncio.Semaphore`, ~5–8) running each tenant's blocking
   work via `asyncio.to_thread`; update job + task rows as they finish. Respect Twilio
   purchase rate limits (cap concurrency, backoff on 429).
6. **`routers/provisioning.py`** — the 3 admin endpoints above (`Depends(deps.require_admin)`),
   kicking the worker via `create_tracked_task`. Submit returns immediately.
7. Deprecate/redirect the old synchronous bulk endpoint to the job API.

## Robustness notes

- In-process async worker on a single web instance: if the instance restarts
  mid-job, tasks stay `pending`/`running` in the DB — the **resume endpoint** re-runs
  them (idempotent steps make this safe). Good enough for an operator-triggered flow;
  upgrade to a Redis-backed worker only if onboarding must survive restarts unattended.
- Twilio purchase **spends money** and is rate-limited — cap concurrency, and never
  re-buy for a tenant that already has a number (step 2 guard).
- Validate the whole payload (dup client_ids/emails, area codes) **before** creating
  the job, so obviously-bad input fails fast at submit.

## Steady-state scaling (separate, also needed for 60+ — schedule alongside)

- **Voice prewarm → lazy** (synthesize on first call; don't sweep all tenants at boot).
- **Cron reminders → bounded concurrency, drop blocking sleeps, shard tenants/run.**
- **Admin list-tenants N+1** → batch/cache the per-tenant Clerk lookups.
- See also `backend/docs/DB-CONCURRENCY.md` — concurrent onboarding is its trigger.
