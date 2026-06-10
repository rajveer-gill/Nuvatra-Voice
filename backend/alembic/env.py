"""Alembic environment.

This project uses raw psycopg2 (no SQLAlchemy ORM models), so migrations are
hand-written with ``op.execute(...)`` and autogenerate is intentionally not
used — ``target_metadata`` is None. The database URL is taken from the
DATABASE_URL environment variable, the same one the app reads, so migrations
always target the app's database.
"""

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

# No ORM metadata — migrations are explicit SQL. Autogenerate is a no-op.
target_metadata = None


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set; Alembic needs it to locate the database. "
            "Set it to the same value the app uses (see docs/MIGRATIONS.md)."
        )
    # Render/Heroku hand out 'postgres://' URLs; SQLAlchemy requires the
    # 'postgresql://' scheme. Normalize so the same env var works everywhere.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection (``alembic upgrade --sql``)."""
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
