"""DB-concurrency reproduction (the gate for the connection-layer rework).

Two concurrent async tasks on the event loop currently share ONE thread-local
connection — the hazard documented in docs/DB-CONCURRENCY.md. This test asserts
the DESIRED behavior (each request gets its own connection) and is marked xfail,
so it documents the defect today and flips to xpass the moment the contextvar
rework lands (at which point remove the xfail and it's a permanent guard).

Requires DATABASE_URL (real Postgres) — _get_conn returns None without USE_DB.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import database

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL required (needs real Postgres)"
)


@pytest.mark.xfail(
    reason="thread-local connection is shared across concurrent async tasks; "
    "fixed by the contextvar per-request connection rework (DB-CONCURRENCY.md)",
    strict=False,
)
def test_concurrent_async_tasks_get_distinct_connections():
    database.init_db()

    async def scenario():
        seen: list[int] = []

        async def one():
            conn = database._get_conn()
            await asyncio.sleep(0.05)  # yield so the other task interleaves
            seen.append(id(conn))
            database._discard_thread_connection()

        await asyncio.gather(one(), one())
        return seen

    ids = asyncio.run(scenario())
    # DESIRED: a per-request connection means the two concurrent tasks hold
    # DISTINCT connection objects. Today they share one (thread-local on the loop
    # thread), so this assertion xfails until the rework.
    assert ids[0] != ids[1]
