# DB concurrency model — finding & fix design

**Status:** open finding (not yet fixed). Safe at low concurrency; a correctness +
throughput risk under real load. Do **not** apply the "obvious" fix below without
the connection-lifecycle rework, or you will make it worse.

## Current model

- `database.py` uses **psycopg2** (synchronous) with a `ThreadedConnectionPool`.
- A connection is cached per OS thread in `_thread_local.conn` (`_get_conn`), and
  returned to the pool by `db_release_thread_connection()`.
- Connections are **not autocommit** — db_* functions call `.commit()` /
  `.rollback()` explicitly (42 commit sites).
- Release happens in an **async** middleware (`db_connection_release_middleware`),
  i.e. on the **event-loop thread**, after each HTTP request.
- The DB-touching route handlers are **`async def`** (e.g. get_appointments,
  create_appointment, get_subscription, get_stats) and call sync db_* directly.

## Why it's a problem

`async def` handlers run on the single event-loop thread, so all requests share
**one** `_thread_local.conn`.

1. **Throughput ceiling (definite).** Every db_* call blocks the event loop. Under
   concurrency, requests can't progress during anyone's DB call — they serialize.
   Invisible at a few simultaneous users; a hard wall under load.

2. **Connection-sharing hazard (real, conditional).** A handler that does
   `db_call → await (OpenAI/httpx) → db_call` yields the loop at the `await` while
   holding the shared connection. A second request can then run, reuse the *same*
   connection (mid-transaction), commit/release it, and corrupt the first request's
   transaction state. At-risk paths: conversation / voice / SMS handlers that mix
   DB with awaited network I/O. Pure `db(); return` handlers (most CRUD) don't yield
   and are currently safe — they just block the loop.

## Why the "obvious" fix is WRONG here

Converting the handlers to sync `def` (so FastAPI runs them in its threadpool) does
**not** work with the current connection lifecycle:

- A sync handler borrows its connection into a **worker thread's** `_thread_local`.
- The release middleware is async and runs on the **event-loop thread**, so it
  releases the wrong thread's connection (`None`). The worker thread's connection is
  never returned to the pool — it's cached on that worker thread and reused across
  unrelated requests, carrying **stale uncommitted transaction state**, and the pool
  drains as worker threads each hold a connection hostage.

So the handler concurrency model and the connection lifecycle must be fixed
**together**, not independently.

## Recommended fixes (pick one; all need load-test validation)

1. **Per-request connection via a FastAPI dependency with `yield`** (recommended,
   smallest blast radius). Acquire the connection in a `Depends` that `yield`s and
   releases in its teardown — teardown runs in the *same execution context* as the
   handler (works for both sync and async). Drop the thread-local caching for request
   paths; keep it only for background/cron threads. Then sync `def` handlers become
   safe and stop blocking the loop.
2. **Async driver (`asyncpg` + async pool).** Cleanest long-term; largest change.
   Handlers stay `async def` and `await` real async DB calls — no loop blocking, no
   thread-local games.
3. **autocommit + short explicit transactions**, combined with per-request release in
   the correct context. Reduces the stale-transaction window but doesn't fix loop
   blocking on its own.

## Validation plan (the suite can't prove this)

The pytest suite uses `TestClient`, which issues requests **serially** — it cannot
surface (or regress) the concurrency behavior. Any fix must be validated with:

- A concurrency repro: fire N interleaved requests where a handler does
  `db → await asyncio.sleep → db`, assert no cross-request data bleed and stable
  connection-pool counts.
- A load test (e.g. `locust`/`k6`) against a staging instance with a real Postgres,
  watching p50/p99 latency and `pg_stat_activity` connection counts.

## Severity

Low risk at current (salon-booking) concurrency; a genuine architectural defect under
real load and a definite finding against a "Google/Meta" review bar. Schedule as its
own workstream with staging load tests — separate from the main.py router refactor,
which is about file structure, not the connection layer.

## Sharpened fix (diagnosed) — the thread-local model is the root cause

Converting handlers to `def` does NOT fix it: FastAPI's threadpool does not pin a
thread per request, so a worker-thread connection gets reused across requests
carrying transaction state, and a `Depends`-with-`yield` teardown can run on a
different worker thread than the handler. The correct fix is to make the per-request
connection follow the *request context*, not the thread:

1. In `database.py`, replace the `_thread_local` connection with a **`contextvars.ContextVar`**
   (anyio copies contextvars into the threadpool, so it follows both async tasks and
   sync handlers). `_get_conn`/release read/write the contextvar.
2. Acquire/release per request via a **request-scoped dependency with `yield`** (or
   keep a middleware, but the contextvar makes release correct in any context). Drop
   the event-loop-thread async release middleware.
3. Then DB-bound CRUD handlers can be plain `def` (threadpooled, no event-loop block),
   and there is no cross-request connection sharing.

This is the **highest-blast-radius change in the codebase** (every endpoint's DB
access). Do NOT rush it — it requires the load test below.

## Local validation runbook (ready now)

- Throwaway Postgres: `docker run -d --name csurge-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=postgres -p 5432:5432 postgres:16`
- Run the DB-integration suite (isolated per conftest): `DATABASE_URL=postgresql://postgres:dev@localhost:5432/postgres python3.9 -m pytest -q` → 384 passed / 0 failed.
- DATABASE_URL is intentionally NOT in `.env` (it would make the unit suite hit real PG); pass it inline for DB runs.

## Progress
- [x] **Step 1 — DB-integration test isolation** (conftest clean-slate; commit 434c22f). Makes the rework verifiable.
- [ ] Step 2 — concurrency reproduction test (httpx.AsyncClient, db→await→db, assert no cross-request bleed) — the gate.
- [ ] Step 3 — implement the contextvar connection rework.
- [ ] Step 4 — repro passes + full suite green + load test (locust/k6, watch `pg_stat_activity`).
- [ ] Step 5 — staged deploy, watched.
