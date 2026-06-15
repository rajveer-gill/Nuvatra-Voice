"""Slot-reservation concurrency: the unique-index claim returns False on conflict,
and booking_service.reserve_slot surfaces that so a second simultaneous booking of the
same slot can't double-book."""

from unittest.mock import MagicMock, patch

import database as db
import booking_service


def _mock_conn(rowcount):
    cur = MagicMock()
    cur.rowcount = rowcount
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


def test_db_booked_slot_reserve_true_on_insert():
    conn, cur = _mock_conn(rowcount=1)  # row inserted = slot was free
    with patch.object(db, "_get_conn", return_value=conn), patch.object(db, "_client_id", return_value="t1"):
        assert db.db_booked_slot_reserve("2026-07-01", "10:00", 5, 30, None) is True
    assert conn.commit.called


def test_db_booked_slot_reserve_false_on_conflict():
    conn, cur = _mock_conn(rowcount=0)  # ON CONFLICT DO NOTHING -> nothing inserted
    with patch.object(db, "_get_conn", return_value=conn), patch.object(db, "_client_id", return_value="t1"):
        assert db.db_booked_slot_reserve("2026-07-01", "10:00", 6, 30, None) is False


def test_reserve_slot_returns_false_when_slot_taken(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(booking_service, "_invalidate_booked_slots_cache", lambda: None)
    calls = {}

    def fake_reserve(date, time, aid, dur, staff):
        calls["args"] = (date, time, aid, dur, staff)
        return False  # simulate slot already claimed by a concurrent booking

    monkeypatch.setattr(booking_service.database, "db_booked_slot_reserve", fake_reserve)
    ok = booking_service.reserve_slot("2026-07-01", "10:00", 7, 30, None)
    assert ok is False
    assert calls["args"] == ("2026-07-01", "10:00", 7, 30, None)


def test_reserve_slot_true_when_db_reserves(monkeypatch):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(booking_service, "_invalidate_booked_slots_cache", lambda: None)
    monkeypatch.setattr(booking_service.database, "db_booked_slot_reserve", lambda *a, **k: True)
    assert booking_service.reserve_slot("2026-07-01", "11:00", 8, 30, None) is True
