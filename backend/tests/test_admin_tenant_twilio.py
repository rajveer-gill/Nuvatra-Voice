"""Admin Twilio phone update endpoint."""
from fastapi.testclient import TestClient

from main import app


def test_twilio_phone_patch_requires_auth():
    client = TestClient(app)
    resp = client.patch(
        "/api/admin/tenants/00000000-0000-0000-0000-000000000001/twilio-phone",
        json={"twilio_phone_number": "+15550001111"},
    )
    assert resp.status_code in (401, 403, 404, 503)
