"""Hard-delete + bulk-clear appointment endpoints (dashboard cleanup).

Delete permanently removes a row and frees its slot, but never texts the customer
(that's what cancel is for). Tenant-scoped.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import booking_service
import database
import deps
from routers import appointments as appts


def _wire(monkeypatch, *, apt=None, delete_ok=True, bulk_count=0):
    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda tenant: "test")
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(database, "db_appointments_get_by_id", lambda aid, client_id=None: (dict(apt) if apt else None))
    deleted = []
    monkeypatch.setattr(database, "db_appointments_delete", lambda aid, client_id=None: deleted.append(aid) or delete_ok)
    monkeypatch.setattr(database, "db_appointments_delete_many", lambda ids, client_id=None: bulk_count)
    released = []
    monkeypatch.setattr(booking_service, "release_slot", lambda aid: released.append(aid))
    monkeypatch.setattr(booking_service, "_invalidate_booked_slots_cache", lambda: None)
    return deleted, released


def test_delete_appointment_success(monkeypatch):
    deleted, released = _wire(monkeypatch, apt={"id": 7, "status": "cancelled"})
    result = appts.delete_appointment(7, request=MagicMock(), tenant={"client_id": "test"})
    assert result == {"success": True, "deleted": True}
    assert deleted == [7]
    assert released == [7]  # slot freed


def test_delete_appointment_404(monkeypatch):
    _wire(monkeypatch, apt=None)
    with pytest.raises(HTTPException) as exc:
        appts.delete_appointment(9, request=MagicMock(), tenant={"client_id": "test"})
    assert exc.value.status_code == 404


def test_bulk_delete_removes_and_frees_slots(monkeypatch):
    _, released = _wire(monkeypatch, bulk_count=3)
    body = appts.AppointmentBulkDeleteBody(ids=[1, 2, 3])
    result = appts.bulk_delete_appointments(body, request=MagicMock(), tenant={"client_id": "test"})
    assert result == {"success": True, "deleted": 3}
    assert released == [1, 2, 3]


def test_bulk_delete_empty_is_noop(monkeypatch):
    _, released = _wire(monkeypatch, bulk_count=0)
    body = appts.AppointmentBulkDeleteBody(ids=[])
    result = appts.bulk_delete_appointments(body, request=MagicMock(), tenant={"client_id": "test"})
    assert result == {"success": True, "deleted": 0}
    assert released == []
