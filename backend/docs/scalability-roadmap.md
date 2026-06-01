# Voice Runtime Scalability Roadmap

## Current Constraints
- `active_calls` and `response_status` are process-local in-memory maps.
- Voice callbacks and media websocket handling assume same-process state continuity.
- Background jobs (summary generation, cache prewarm) run via in-process async tasks.
- Database layer currently relies on a singleton connection pattern.

## Phase A: Shared Runtime State (Redis)
- Introduce Redis-backed call session model for:
  - call metadata (`call_sid`, tenant/client id, language, last utterance)
  - response state (`pending/ready/error`, audio_url)
  - short-lived locks keyed by `call_sid`.
- Add TTL-based lifecycle (e.g. 15-30 minutes) and explicit terminal cleanup.
- Keep in-memory maps as non-authoritative cache during migration.

## Phase B: Background Work Queue
- Move heavy/slow jobs to worker queue:
  - recording summarization
  - cache prewarm refresh tasks
  - optional async compliance/audit enrichment.
- Persist job state and retries.
- Add dead-letter queue with alerting.

## Phase C: Data Layer Hardening
- Replace singleton DB connection with pooled driver (`psycopg_pool` or SQLAlchemy engine pool).
- Add retry policy for transient connection failures.
- Add per-query timeout and circuit-breaker style metrics.

## Phase D: Operational Readiness
- Add service-level metrics and SLOs:
  - webhook reject rates by reason
  - TwiML response latency
  - call state orphan count
  - background task failure rate.
- Add runbooks for:
  - tenant resolution failures
  - signature validation failures
  - Redis/DB outage modes.

## Migration Notes
- Roll out Redis state with dual-write then read-switch.
- Keep strict webhook/auth behavior unchanged during scale migration.
- Validate with staged load tests using representative Twilio callback concurrency.
