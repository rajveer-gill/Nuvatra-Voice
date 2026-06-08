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
