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

**Caveat discovered (read before implementing):** a ContextVar correctly follows
*async* tasks, but `run_in_threadpool` (used for sync `def` handlers) runs in a
*copied* context — mutations there do NOT propagate back to the caller, so an outer
(middleware) release won't see a connection acquired inside the threadpool. So the
connection must be **acquired AND released within the same execution unit** (e.g. a
single dependency whose setup and teardown both run in-context, or the handler
itself), not split across a copied-context boundary. If that proves fiddly, the
clean answer is **asyncpg + an async pool** (connection naturally bound to the async
task; no thread games). Decide async-driver vs contextvar at the start of step 3 —
the reproduction test (step 2) is the correctness gate either way.

## Local validation runbook (ready now)

- Throwaway Postgres: `docker run -d --name csurge-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=postgres -p 5432:5432 postgres:16`
- Run the DB-integration suite (isolated per conftest): `DATABASE_URL=postgresql://postgres:dev@localhost:5432/postgres python3.9 -m pytest -q` → 384 passed / 0 failed.
- DATABASE_URL is intentionally NOT in `.env` (it would make the unit suite hit real PG); pass it inline for DB runs.

## Progress
- [x] **Step 1 — DB-integration test isolation** (conftest clean-slate; commit 434c22f). Makes the rework verifiable.
- [x] **Step 2 — concurrency reproduction test** (test_db_concurrency_repro.py, xfail — documents the live defect).
- [~] **Step 3a — contextvar connection rework: ATTEMPTED, then REVERTED.** See post-mortem (attempt 1) below.
- [x] **Step 3b — per-call connection scoping (attempt 2): LANDED.** See "The fix that shipped" below.
- [~] **Step 4 — throughput half: bulk landed (commit a6efd6c).** 62 of 78 request handlers were
      pure blocking work (no `await` in the body); converted `async def` → `def` so FastAPI runs them
      in its threadpool, moving their DB work off the event loop. Safe on top of 3b (each db_* call is
      a self-contained borrow+release unit). **Still on the loop (follow-ups):**
      (a) the 13 "mixed" handlers that genuinely `await` (OpenAI/httpx/gather) — wrap their individual
          db_* calls in `await asyncio.to_thread(...)`;
      (b) the async auth dependencies (`require_tenant` etc.) that do a lookup per request;
      (c) 3 handlers kept async by necessity (they schedule background tasks → need a running loop).
- [ ] Step 5 — load test (locust/k6 against staging; watch p50/p99 + `pg_stat_activity`). **Required to
      validate ANY of step 4** — the serial pytest suite (TestClient) cannot surface throughput.
- [ ] Step 6 — staged deploy, watched.

### Converting handlers to sync `def` — the rule that matters
A sync `def` runs in a threadpool worker **with no running event loop**, so a handler may be made
sync ONLY if it (transitively) never needs the loop. Classification: no `await`/`async with`/
`async for` in the body AND no transitive `asyncio.create_task` / `create_tracked_task` /
`get_running_loop`. The trap is *transitive* scheduling — e.g. `create_provisioning_job` has no
`await` in its body but calls `_kick_worker()` → `asyncio.create_task`; converting it broke its test.
When in doubt, leave it async.

## The fix that shipped (attempt 2 — per-call connection scoping)

**Insight.** The bleed only ever happens when a connection is **cached across an `await`**. A db_*
body is synchronous and contains no `await`, so if each *top-level* db_* call borrows a dedicated
pooled connection and returns it the instant it returns, the connection is never held across a
yield point — concurrent async requests can never share a live connection. Crucially, borrow and
release then happen in the **same synchronous call frame**, so nothing depends on framework/
middleware teardown running in the right context (the exact failure mode of attempt 1).

**Implementation (all in `database.py`, ~90 lines, zero call-site / handler / background-worker
changes):**
- `_scoped(fn)` wraps a db_* function: on a no-DB path (`not _use_db`) it's a pass-through;
  otherwise it bumps a `_thread_local.depth` counter, runs the body, and on the outermost frame
  (depth back to 0) calls `_conn_scope_exit()`.
- `_conn_scope_exit()` rolls back the borrowed connection (clears any idle-in-transaction read
  snapshot; committed writes are already persisted) and returns it to the pool — discarding it on
  error rather than poisoning the pool.
- A module-bottom loop wraps all 94 public `db_*` functions in place (rebinding the globals, so
  inter-function calls like `db_tenant_member_add → db_tenant_member_assign_owner` also go through
  the scope; the depth counter keeps a nested chain on one shared connection, released once by the
  outermost frame). `db_release_thread_connection` is excluded (it's the explicit release helper).

**Why this is correct for every execution context:**
- *Async handlers* (the buggy path): each db_* borrows+releases atomically on the loop thread;
  since the call is synchronous it can't be interrupted mid-borrow, and the conn is gone before any
  `await`. No cross-request bleed.
- *Background `to_thread` workers* (provisioning/cron 60+ fan-out, recording summary, voice warm):
  unchanged — each runs on its own OS thread; per-call scoping just makes their explicit
  `db_release_thread_connection()` redundant (harmless no-op).
- *Tests calling handlers/db_* directly*: each call self-releases, so the attempt-1 leak (no
  TestClient → no teardown → leak) cannot recur.

**Verified:** after any top-level db_* call `_thread_local.conn is None` (released, depth 0); two
concurrent async tasks doing db→await→db hold no connection across the await; 50 sequential calls
do not exhaust the pool; unit suite green (386 + the 1 pre-existing clock-brittle booking test);
full DB-integration suite green at ~70s (no pool exhaustion — the gate that attempt 1 failed).

> Note: `test_db_concurrency_repro.py` stays `xfail` — it probes the *low-level* `_get_conn()`
> directly (still thread-local by design), not the db_* boundary where the fix lives. The real
> protection is the borrow-per-call discipline above, covered by the DB-integration suite.

## Post-mortem — why the contextvar rework was reverted (attempt 1)

**What was tried.** Replace `database._thread_local` (per-OS-thread) with
`database._conn_var = contextvars.ContextVar("db_conn")` (per-task), so each async task gets its
own connection; move the connection RELEASE from the `@app.middleware("http")` hook to a
`_db_request_scope()` **yield-dependency** on `FastAPI(dependencies=...)`, on the theory its
teardown runs in the handler's own context and can therefore see the contextvar.

**The correctness half worked.** A direct probe (two `asyncio.gather`'d tasks each calling
`_get_conn()`) confirmed they now receive DISTINCT connection objects — the cross-request
transaction-bleed hazard is genuinely fixable this way.

**The release half did NOT.** Running the full DB-integration suite under the rework:
`134 passed, 258 errors in 2609s (43m)` — vs. `391 passed in ~70s` before. Signature of
**connection-pool exhaustion**: connections were borrowed and never returned, the
`ThreadedConnectionPool(maxconn=10)` drained, and every later test errored/stalled. Two leak
sources, both real:
1. **Tests (and internal code) that call handler functions directly** — not through TestClient —
   borrow a connection in `_get_conn()` but never trigger the request-scoped yield-dependency, so
   nothing releases it. The old thread-local model survived this because conftest's per-test
   `_discard_thread_connection()` cleaned the single shared thread-local conn; with a contextvar,
   the conn lives in whatever (possibly already-exited) context borrowed it.
2. **The yield-dependency teardown does not reliably see the handler's `_conn_var.set()`** —
   Starlette/anyio runs portions of the request in copied contexts, so a contextvar mutation made
   deep in the handler is not always visible at dependency-teardown time. This is the same
   copied-context hazard the plan flagged for `run_in_threadpool`; it applies here too.

**Decision.** Reverted database.py + main.py to the thread-local model (known-good, 391 green).
A connection layer that leaks under the real call patterns is strictly worse than the documented,
contained defect. The repro test stays `xfail` (it still documents the live hazard).

**The real path (attempt 2).** Don't bolt per-task lifecycle onto a sync psycopg2 pool with
contextvars + framework teardown hooks — the acquire/release boundary is too implicit. Either:
- **(preferred) migrate the DB layer to `asyncpg`** with an explicit per-request
  `async with pool.acquire() as conn` scope — acquire and release are lexically bound and
  context-correct by construction; or
- keep psycopg2 but make acquire/release **explicit at every entry point** (a context-manager
  dependency for HTTP routes AND an explicit `with db_conn():` wrapper around every direct/
  background call site), never relying on middleware/teardown to find a contextvar.

Either way, the gate is the same: the repro test flips to pass AND the full DB-integration suite
stays green at ~70s (no pool exhaustion), THEN a staging load test.
