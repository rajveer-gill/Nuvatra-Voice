"""Pytest fixtures for backend tests."""
import os
import pytest

# Avoid loading real env; use test values
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake")
os.environ.setdefault("CLIENT_ID", "default")
# Force in-memory voice state for unit tests (production uses REDIS_URL without this).
os.environ.setdefault("VOICE_STATE_BACKEND", "memory")


@pytest.fixture
def client():
    """FastAPI TestClient."""
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


# --- DB-integration test isolation --------------------------------------------
# When DATABASE_URL is set (local Postgres / staging), the DB-integration tests
# (pytest.mark.skipif(not DATABASE_URL)) run against real Postgres on a shared
# database. Without isolation they pollute each other. These fixtures ensure the
# schema exists once, then give every test a clean slate. No-ops in the normal
# unit run (DATABASE_URL empty), so CI behavior is unchanged.


@pytest.fixture(scope="session", autouse=True)
def _db_schema_ready():
    if os.getenv("DATABASE_URL"):
        import database

        database.init_db()  # CREATE TABLE IF NOT EXISTS — idempotent
    yield


@pytest.fixture(autouse=True)
def _db_clean_slate():
    url = os.getenv("DATABASE_URL")
    if not url:
        yield
        return
    import psycopg2
    import database

    # Drop any pooled connection a prior test left holding a txn/lock, so the
    # TRUNCATE below (ACCESS EXCLUSIVE) can't deadlock against it.
    try:
        database._discard_thread_connection()
    except Exception:
        pass
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET lock_timeout = '10s'")
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    tables = [r[0] for r in cur.fetchall()]
    if tables:
        cur.execute(
            "TRUNCATE TABLE "
            + ", ".join('"%s"' % t for t in tables)
            + " RESTART IDENTITY CASCADE"
        )
    cur.close()
    conn.close()
    yield
