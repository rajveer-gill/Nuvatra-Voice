"""Tests for inbound MMS photo capture + the authenticated media proxy."""

import os
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

import database
import deps
import runtime
from routers import core, sms


# ---- capture ----

def test_extract_inbound_media_keeps_images_only():
    form = {
        "NumMedia": "2",
        "MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages/MM1/Media/MEabc123",
        "MediaContentType0": "image/jpeg",
        "MediaUrl1": "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages/MM1/Media/MEpdf456",
        "MediaContentType1": "application/pdf",
    }
    out = sms._extract_inbound_media(form)
    assert len(out) == 1  # the PDF is dropped
    assert out[0]["sid"] == "MEabc123"
    assert out[0]["content_type"] == "image/jpeg"
    assert out[0]["url"].endswith("MEabc123")


def test_extract_inbound_media_none():
    assert sms._extract_inbound_media({"NumMedia": "0"}) == []
    assert sms._extract_inbound_media({}) == []
    assert sms._extract_inbound_media({"NumMedia": "junk"}) == []


# ---- secure proxy ----

def _setup(monkeypatch, media):
    monkeypatch.setattr(runtime, "USE_DB", True)
    monkeypatch.setattr(core, "_tenant_has_messages", lambda t: True)
    monkeypatch.setattr(deps, "_bind_tenant_db_context", lambda t: "c-1")
    monkeypatch.setattr(
        database, "db_sms_session_get",
        lambda phone, cid: {"messages": [{"role": "user", "content": "here", "media": media}]},
    )
    os.environ["TWILIO_ACCOUNT_SID"] = "AC1"
    os.environ["TWILIO_AUTH_TOKEN"] = "tok"


def _teardown():
    os.environ.pop("TWILIO_ACCOUNT_SID", None)
    os.environ.pop("TWILIO_AUTH_TOKEN", None)


def test_media_proxy_streams_the_image(monkeypatch):
    _setup(monkeypatch, [{"sid": "ME1", "url": "https://api.twilio.com/x/Media/ME1", "content_type": "image/png"}])
    monkeypatch.setattr(httpx, "get", lambda url, **kw: MagicMock(status_code=200, content=b"PNGBYTES"))
    try:
        resp = core.get_sms_media(phone="+15551110000", sid="ME1", tenant={"client_id": "c-1"})
        assert resp.body == b"PNGBYTES"
        assert resp.media_type == "image/png"
    finally:
        _teardown()


def test_media_proxy_rejects_unknown_sid(monkeypatch):
    # SSRF / IDOR guard: only a sid actually stored in this tenant's thread resolves.
    _setup(monkeypatch, [{"sid": "ME1", "url": "https://api.twilio.com/x/Media/ME1", "content_type": "image/png"}])
    try:
        with pytest.raises(HTTPException) as exc:
            core.get_sms_media(phone="+15551110000", sid="ME_attacker", tenant={"client_id": "c-1"})
        assert exc.value.status_code == 404
    finally:
        _teardown()


def test_media_proxy_rejects_non_image(monkeypatch):
    _setup(monkeypatch, [{"sid": "ME1", "url": "https://api.twilio.com/x/Media/ME1", "content_type": "application/pdf"}])
    try:
        with pytest.raises(HTTPException) as exc:
            core.get_sms_media(phone="+15551110000", sid="ME1", tenant={"client_id": "c-1"})
        assert exc.value.status_code == 400
    finally:
        _teardown()
