"""db_ping must survive a stale pooled connection (Render closes idle conns),
so a transient bad connection doesn't flap the health check into a 503."""

from __future__ import annotations

from unittest.mock import MagicMock

import database


def test_db_ping_retries_with_fresh_connection_on_stale(monkeypatch):
    """First borrowed connection is dead (SELECT 1 raises); db_ping should discard
    it, get a fresh one, and return True."""
    dead = MagicMock()
    dead.cursor.return_value.execute.side_effect = OSError("server closed the connection")
    good = MagicMock()  # good.cursor().execute() just succeeds

    conns = [dead, good]
    monkeypatch.setattr(database, "_get_conn", lambda: conns.pop(0) if conns else good)
    discarded = {"n": 0}
    monkeypatch.setattr(
        database, "_discard_thread_connection", lambda: discarded.__setitem__("n", discarded["n"] + 1)
    )

    assert database.db_ping() is True
    assert discarded["n"] == 1  # the dead connection was discarded once


def test_db_ping_false_when_db_truly_down(monkeypatch):
    """No connection available on either attempt -> False (real outage -> 503)."""
    monkeypatch.setattr(database, "_get_conn", lambda: None)
    assert database.db_ping() is False


def test_db_ping_ok_first_try(monkeypatch):
    good = MagicMock()
    monkeypatch.setattr(database, "_get_conn", lambda: good)
    assert database.db_ping() is True


def test_get_conn_prepings_and_replaces_stale_pool_connection(monkeypatch):
    """_get_conn validates a pooled connection (SELECT 1) and, if it's a dead
    idle connection, discards it (putconn close=True) and borrows a fresh one."""
    dead = MagicMock()
    dead.closed = False
    dead.cursor.return_value.execute.side_effect = OSError("server closed the connection")
    good = MagicMock()
    good.closed = False
    pool = MagicMock()
    pool.getconn.side_effect = [dead, good]

    monkeypatch.setattr(database, "_use_db", True)
    monkeypatch.setattr(database, "_ensure_pool", lambda: pool)
    database._thread_local.conn = None

    try:
        result = database._get_conn()
        assert result is good
        pool.putconn.assert_called_once_with(dead, close=True)
    finally:
        database._thread_local.conn = None


def test_get_conn_returns_none_when_all_pool_connections_stale(monkeypatch):
    dead = MagicMock()
    dead.closed = False
    dead.cursor.return_value.execute.side_effect = OSError("server closed")
    pool = MagicMock()
    pool.getconn.return_value = dead

    monkeypatch.setattr(database, "_use_db", True)
    monkeypatch.setattr(database, "_ensure_pool", lambda: pool)
    database._thread_local.conn = None
    try:
        assert database._get_conn() is None
    finally:
        database._thread_local.conn = None
