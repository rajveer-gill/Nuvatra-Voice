# Database strategy (PostgreSQL)

## Current approach (v1)

- **Schema bootstrap**: `init_db()` in [`backend/database.py`](../backend/database.py) runs `CREATE TABLE IF NOT EXISTS` for tenants, appointments, usage, SMS opt-out, and related tables. This keeps fresh environments simple and matches Render’s container-style deploys.
- **Access layer**: SQL lives alongside helpers in `database.py` (single module, ~1.4k lines). Call sites import functions explicitly (e.g. `db_appointments_insert`).
- **Rationale**: Fast to ship, minimal operational overhead, works well for a single Postgres instance.

## When to introduce Alembic

Consider **Alembic** migrations when any of the following are true:

- You need **non-additive** changes (rename column, data backfills, constrained ALTERs) with reviewable upgrade/downgrade scripts.
- Multiple developers or services apply schema changes independently.
- You must **replay** production schema history on staging reliably.

Alembic adds process: migration reviews, upgrade ordering, and CI checks. Plan a focused sprint to move `init_db()` DDL into revision `0001_initial` and freeze new tables via migrations going forward.

## Pragmatic split (optional, short term)

Before Alembic, you can split `database.py` **by domain** (e.g. `db/tenants.py`, `db/appointments.py`) behind a thin `db/__init__.py` re-export to reduce merge conflicts without changing behavior.

## Decision

| Option | Status |
|--------|--------|
| `CREATE TABLE IF NOT EXISTS` in `init_db()` | **Active** — production path on Render |
| Alembic | **Deferred** until destructive migrations are required |
| Domain split of `database.py` | **Optional** refactor when touching DB layer heavily |
