"""Admin referral endpoints: auth, create/list codes, payouts, mark-paid."""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_referral_endpoints_require_auth(client):
    assert client.post("/api/admin/referral-codes", json={"code": "X", "referrer_name": "Y"}).status_code in (401, 403)
    assert client.get("/api/admin/referral-codes").status_code in (401, 403)
    assert client.get("/api/admin/referral-commissions").status_code in (401, 403)
    assert client.patch("/api/admin/referral-commissions/1", json={"paid": True}).status_code in (401, 403)


def test_create_code_and_duplicate(client, monkeypatch):
    import database, deps, runtime
    from deps import require_admin

    monkeypatch.setattr(runtime, "USE_DB", True)
    audits = []
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: audits.append(a))
    # First create succeeds (returns id), second returns None (duplicate).
    seq = iter([7, None])
    monkeypatch.setattr(database, "db_referral_code_create", lambda *a, **k: next(seq))
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        ok = client.post("/api/admin/referral-codes", json={"code": "jane", "referrer_name": "Jane Doe"})
        assert ok.status_code == 200
        assert ok.json()["code"] == "JANE"  # normalized uppercase
        assert any(a[:2] == ("admin", "referral_code_created") for a in audits)
        dup = client.post("/api/admin/referral-codes", json={"code": "jane", "referrer_name": "Jane Doe"})
        assert dup.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_create_code_rejects_bad_chars(client, monkeypatch):
    import runtime
    from deps import require_admin

    monkeypatch.setattr(runtime, "USE_DB", True)
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        bad = client.post("/api/admin/referral-codes", json={"code": "a b!", "referrer_name": "Jane"})
        assert bad.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_list_codes_with_counts(client, monkeypatch):
    import database, runtime
    from deps import require_admin

    monkeypatch.setattr(runtime, "USE_DB", True)
    monkeypatch.setattr(
        database, "db_referral_codes_list_with_counts",
        lambda: [{"id": 1, "code": "JANE", "referrer_name": "Jane", "active": True,
                  "signups": 3, "converted": 2, "flagged": 0}],
    )
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        r = client.get("/api/admin/referral-codes")
        assert r.status_code == 200
        assert r.json()["codes"][0]["converted"] == 2
    finally:
        app.dependency_overrides.clear()


def test_list_commissions_totals(client, monkeypatch):
    import database, runtime
    from deps import require_admin

    monkeypatch.setattr(runtime, "USE_DB", True)
    monkeypatch.setattr(
        database, "db_referral_commissions_list_all",
        lambda include_paid=True: [
            {"id": 1, "kind": "signup_bounty", "amount_cents": 20000, "paid": False,
             "code_snapshot": "JANE", "referrer_name": "Jane", "business_name": "Acme",
             "plan_snapshot": "growth", "period_key": "signup", "paid_at": None, "created_at": None},
            {"id": 2, "kind": "mrr", "amount_cents": 6250, "paid": True,
             "code_snapshot": "JANE", "referrer_name": "Jane", "business_name": "Acme",
             "plan_snapshot": "growth", "period_key": "in_1", "paid_at": None, "created_at": None},
        ],
    )
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        r = client.get("/api/admin/referral-commissions")
        assert r.status_code == 200
        body = r.json()
        assert body["unpaid_total_cents"] == 20000
        assert body["paid_total_cents"] == 6250
    finally:
        app.dependency_overrides.clear()


def test_referral_validate_works_for_signed_in_user_without_tenant(client, monkeypatch):
    """The signup-page validate endpoint must work for a signed-in user who has no tenant
    yet (require_user, not require_tenant) — regression for the 403 banner bug."""
    import database
    import runtime
    from deps import require_user

    monkeypatch.setattr(runtime, "USE_DB", True)
    monkeypatch.setattr(database, "db_referral_code_get_by_code",
                        lambda code, active_only=True: {"id": 1, "referrer_name": "Final Test"})
    # Signed-in user but NO tenant — this previously 403'd under require_tenant.
    app.dependency_overrides[require_user] = lambda: "user_abc"
    try:
        r = client.get("/api/referral/validate?code=LAUNCH")
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is True
        assert body["referrer_first_name"] == "Final"  # first name only, no contact/terms
    finally:
        app.dependency_overrides.clear()


def test_referral_validate_requires_auth(client):
    assert client.get("/api/referral/validate?code=LAUNCH").status_code in (401, 403)


def test_mark_commission_paid_audits(client, monkeypatch):
    import database, deps, runtime
    from deps import require_admin

    monkeypatch.setattr(runtime, "USE_DB", True)
    audits = []
    monkeypatch.setattr(deps, "audit_log", lambda *a, **k: audits.append(a))
    monkeypatch.setattr(database, "db_referral_commission_mark_paid", lambda cid: True)
    app.dependency_overrides[require_admin] = lambda: "admin-test"
    try:
        r = client.patch("/api/admin/referral-commissions/5", json={"paid": True})
        assert r.status_code == 200
        assert r.json() == {"success": True, "paid": True}
        assert any(a[:2] == ("admin", "referral_commission_paid") for a in audits)
    finally:
        app.dependency_overrides.clear()
