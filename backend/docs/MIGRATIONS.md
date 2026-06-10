# Database migrations (Alembic)

The schema is versioned with [Alembic](https://alembic.sqlalchemy.org/). This
replaces the old pattern of adding `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE
... ADD COLUMN IF NOT EXISTS` statements inside `database.init_db()`.

**The rule going forward: every schema change is a new Alembic revision. Do not
add new DDL to `init_db()`.**

All commands run from `backend/` and read the database from the `DATABASE_URL`
environment variable (the same one the app uses). Render/Heroku `postgres://`
URLs are normalized to `postgresql://` automatically.

## Layout

```
backend/
  alembic.ini                       # config (URL comes from env, not here)
  alembic/
    env.py                          # reads DATABASE_URL; raw-SQL, no ORM models
    script.py.mako                  # template for new revisions
    versions/
      0001_baseline.py              # snapshot of the schema at adoption
```

There are no SQLAlchemy models — migrations are hand-written with
`op.execute("<SQL>")`, matching the rest of the raw-psycopg2 data layer.

## One-time setup for existing databases

`0001_baseline` reproduces the exact schema that `init_db()` built (verified by
diffing `pg_dump` of an `init_db`-built database against an
`alembic upgrade head`-built one — identical). An already-running database
therefore already *has* this schema, so do **not** run `upgrade` against it.
Instead, record that it sits at the baseline:

```bash
alembic stamp 0001_baseline
```

`stamp` only writes the version marker; it runs no DDL and never touches your
data. Do this once per existing environment (production, staging, any dev DB
that was built by `init_db`).

A brand-new, empty database is built with:

```bash
alembic upgrade head
```

## Creating a new migration

```bash
# 1. scaffold (use a clear message; --rev-id keeps the 000N ordering)
alembic revision -m "add appointments.notes" --rev-id 0002

# 2. edit alembic/versions/0002_add_appointments_notes.py — fill in upgrade()
#    and downgrade() with op.execute("...") statements, e.g.:
#      def upgrade():
#          op.execute("ALTER TABLE appointments ADD COLUMN notes TEXT")
#      def downgrade():
#          op.execute("ALTER TABLE appointments DROP COLUMN notes")

# 3. apply locally and verify
alembic upgrade head
alembic current        # shows the applied revision

# 4. commit the new version file
```

Always write a real `downgrade()` so the migration is reversible.

## Applying migrations in deployment

This adoption is **additive**: `init_db()` is unchanged and still bootstraps the
schema at app startup, so the running deploy was not modified. To apply a *new*
migration to production, run `alembic upgrade head` against the production
`DATABASE_URL` — either manually, or by wiring it into a release step (e.g. a
Render pre-deploy command or a `release:` Procfile entry). Run it as a single
release step, not from every web worker, to avoid concurrent-migration races.

## Useful commands

```bash
alembic current            # what revision is this DB at?
alembic history --verbose  # list all revisions
alembic upgrade head       # apply everything pending
alembic downgrade -1       # roll back one revision
alembic upgrade head --sql # print SQL without running it (offline/review)
```
