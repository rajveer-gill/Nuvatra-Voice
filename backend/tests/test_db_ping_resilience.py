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
