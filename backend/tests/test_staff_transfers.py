"""Unit tests for staff_transfers module."""
from staff_transfers import (
    finalize_transfer_targets_for_storage,
    get_transfer_phone_by_name,
    resolve_transfer_destinations,
    TransferTarget,
)


def test_resolve_transfer_targets_linked_staff_phone_authoritative():
    info = {
        "staff": [{"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "name": "Jamie", "phone": "+15559876543"}],
        "transfer_targets": [
            {
                "id": "11111111-2222-3333-4444-555555555555",
                "staff_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "name": "Jamie",
                "phone": "+15551111111",
            }
        ],
    }
    dests = resolve_transfer_destinations(info)
    assert len(dests) == 1
    assert dests[0]["phone"] == "+15559876543"


def test_legacy_staff_phones_when_no_transfer_targets():
    info = {
        "staff": [{"id": "a", "name": "Sam", "phone": "+15551234567"}],
        "transfer_targets": [],
    }
    dests = resolve_transfer_destinations(info)
    assert dests[0]["name"] == "Sam"
    assert dests[0]["phone"] == "+15551234567"


def test_get_transfer_phone_by_name():
    info = {
        "transfer_targets": [{"id": "x", "name": "Alex", "phone": "+15552223333"}],
        "staff": [],
    }
    assert get_transfer_phone_by_name("alex", info) == "+15552223333"
    assert get_transfer_phone_by_name("nobody", info) is None


def test_finalize_rejects_duplicate_staff_link():
    staff = [{"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "name": "A", "phone": "+15551111111"}]
    targets = [
        TransferTarget(name="A", phone="+15551111111", staff_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        TransferTarget(name="A2", phone="+15552222222", staff_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
    ]
    try:
        finalize_transfer_targets_for_storage(targets, staff, transfer_max=5)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "once" in str(e).lower()
