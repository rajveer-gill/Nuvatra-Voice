"""Admin invite re-link links every Clerk user returned for an email."""
from unittest.mock import MagicMock

import pytest

import main


def test_clerk_link_email_links_first_user_when_duplicates(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_fake")
    tenant_id = "06aa8575-2968-46ae-8497-80948c38a845"
    user_a = "user_3DKp7y5cIwCXU2x5eKsYSZ9io4S"
    user_b = "user_3Dxq0pNahALvPq9tafn01HNOCst"
    linked: list[str] = []

    monkeypatch.setattr(main, "db_tenant_invite_upsert", lambda *a, **k: True)
    monkeypatch.setattr(main, "db_tenant_invite_delete", lambda *a, **k: None)
    monkeypatch.setattr(main, "_clerk_user_ids_for_email", lambda email, headers: [user_a, user_b])

    def fake_relink(uid, tid, headers):
        linked.append(uid)
        return []

    monkeypatch.setattr(main, "_clerk_relink_user_to_tenant", fake_relink)

    result = main._clerk_link_email_to_tenant("client@acme-salon.com", tenant_id)

    assert result["user_relinked"] is True
    assert result["clerk_users_matched_count"] == 2
    assert result["linked_clerk_user_ids"] == [user_a]
    assert linked == [user_a]
    assert result["linked_clerk_user_id"] == user_a
    assert result["clerk_error"]


def test_clerk_link_email_sends_invite_when_no_users(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(main, "db_tenant_invite_upsert", lambda *a, **k: True)
    monkeypatch.setattr(main, "_clerk_user_ids_for_email", lambda email, headers: [])

    import httpx

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post = MagicMock(return_value=mock_resp)
    monkeypatch.setattr(httpx, "post", mock_post)

    result = main._clerk_link_email_to_tenant("new@acme-salon.com", "tenant-uuid")

    assert result["invite_sent"] is True
    assert result["user_relinked"] is False
    mock_post.assert_called_once()
