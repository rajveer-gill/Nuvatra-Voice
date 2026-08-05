"""Looking up a Clerk account by email must never return somebody else's.

This is the highest-consequence lookup in the codebase. Its result feeds
_clerk_link_email_to_tenant, which takes [0] and runs db_tenant_member_assign_owner
— "make this user the sole owner of the tenant". A wrong answer here doesn't degrade
gracefully; it hands a store to a stranger and evicts whoever had it.

It went wrong in production exactly once, and the mechanism is worth stating plainly:
Clerk ignores query parameters it doesn't recognise and answers with the whole user
list. A request whose filter silently didn't apply is indistinguishable, by shape,
from one where everybody matched. Inviting an address with no account therefore
returned every user in the instance, and the first of them was made owner of the
store. The fix is to stop trusting the filter and check each row's own addresses.
"""

from __future__ import annotations

import pytest

import clerk_service


def _user(uid: str, *emails: str) -> dict:
    return {
        "id": uid,
        "email_addresses": [{"email_address": e} for e in emails],
    }


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


def _api(monkeypatch, payload, status=200):
    """Every Clerk users request answers with `payload`."""
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _Resp(payload, status)

    import httpx

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


# --- The bug ------------------------------------------------------------------


def test_an_ignored_filter_matches_nobody(monkeypatch):
    """THE regression test. Clerk returned the full user list for an address that had
    no account; the caller made users[0] the owner of the store."""
    _api(monkeypatch, {"data": [
        _user("user_a", "someone@else.com"),
        _user("user_b", "another@person.com"),
        _user("user_c", "third@party.com"),
    ]})
    assert clerk_service._clerk_user_ids_from_api("nobody@nowhere.com", {}) == []


def test_only_the_rows_that_own_the_address_are_returned(monkeypatch):
    """A partially-applied filter must not drag the bystanders through."""
    _api(monkeypatch, {"data": [
        _user("user_other", "someone@else.com"),
        _user("user_want", "wanted@co.com"),
        _user("user_other2", "third@party.com"),
    ]})
    assert clerk_service._clerk_user_ids_from_api("wanted@co.com", {}) == ["user_want"]


def test_a_working_filter_still_works(monkeypatch):
    _api(monkeypatch, {"data": [_user("user_want", "wanted@co.com")]})
    assert clerk_service._clerk_user_ids_from_api("wanted@co.com", {}) == ["user_want"]


def test_matching_ignores_case_and_whitespace(monkeypatch):
    _api(monkeypatch, {"data": [_user("user_want", "Wanted@Co.com")]})
    assert clerk_service._clerk_user_ids_from_api("  WANTED@co.COM  ", {}) == ["user_want"]


def test_a_secondary_address_on_the_account_counts(monkeypatch):
    """A Clerk user can hold several addresses; signing in with any of them is them."""
    _api(monkeypatch, {"data": [_user("user_want", "primary@co.com", "alias@co.com")]})
    assert clerk_service._clerk_user_ids_from_api("alias@co.com", {}) == ["user_want"]


def test_several_accounts_sharing_an_address_all_come_back(monkeypatch):
    """Common after OAuth plus a password account. The caller decides what to do."""
    _api(monkeypatch, {"data": [
        _user("user_1", "shared@co.com"),
        _user("user_2", "shared@co.com"),
    ]})
    assert clerk_service._clerk_user_ids_from_api("shared@co.com", {}) == ["user_1", "user_2"]


# --- Degenerate responses -----------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},
        {"data": [{"id": "user_a"}]},                      # no email_addresses at all
        {"data": [{"id": "user_a", "email_addresses": []}]},
        {"data": [{"email_addresses": [{"email_address": "wanted@co.com"}]}]},  # no id
        {"data": [None, "nonsense", 5]},
        {},
        [],
    ],
)
def test_junk_responses_match_nobody(monkeypatch, payload):
    _api(monkeypatch, payload)
    assert clerk_service._clerk_user_ids_from_api("wanted@co.com", {}) == []


def test_an_api_error_matches_nobody(monkeypatch):
    _api(monkeypatch, {"errors": ["nope"]}, status=422)
    assert clerk_service._clerk_user_ids_from_api("wanted@co.com", {}) == []


def test_a_transport_failure_matches_nobody(monkeypatch):
    import httpx

    def boom(url, **kw):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(httpx, "get", boom)
    assert clerk_service._clerk_user_ids_from_api("wanted@co.com", {}) == []


@pytest.mark.parametrize("email", ["", "   ", "not-an-email", "@", None])
def test_a_junk_address_never_reaches_the_api(monkeypatch, email):
    import httpx

    def fail(url, **kw):
        raise AssertionError("should not call Clerk")

    monkeypatch.setattr(httpx, "get", fail)
    assert clerk_service._clerk_user_ids_from_api(email, {}) == []


# --- The consequence ----------------------------------------------------------


def test_no_match_means_nobody_is_made_owner(monkeypatch):
    """The property that actually matters: with no matching account, the invite path
    must send an invitation and touch no memberships."""
    _api(monkeypatch, {"data": [_user("user_bystander", "someone@else.com")]})
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(clerk_service.database, "db_tenant_invite_upsert", lambda *a: True)

    def no(*a, **k):
        raise AssertionError("a non-matching account must never be relinked")

    monkeypatch.setattr(clerk_service.database, "db_tenant_member_assign_owner", no)
    monkeypatch.setattr(clerk_service.deps, "_admin_access_log", lambda *a, **k: None)

    posted = []

    import httpx

    monkeypatch.setattr(
        httpx, "post", lambda url, **kw: posted.append(url) or _Resp({"id": "inv_1"})
    )
    out = clerk_service._clerk_link_email_to_tenant("nobody@nowhere.com", "tenant-1")
    assert out["invite_sent"] is True
    assert out["user_relinked"] is False
    assert any("invitations" in u for u in posted)


def test_emails_on_clerk_user_is_lowercased_and_clean():
    row = _user("u", "  Mixed@Case.COM  ", "", "second@co.com")
    assert clerk_service._emails_on_clerk_user(row) == ["mixed@case.com", "second@co.com"]
