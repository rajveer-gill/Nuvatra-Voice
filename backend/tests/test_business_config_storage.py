"""Business config loads from PostgreSQL before on-disk file (Render persistence)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import main


@pytest.fixture
def client_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_read_raw_client_config_prefers_db(client_config_dir, monkeypatch):
    cid = "test-spa"
    file_cfg = {"client_id": cid, "business_name": "File Spa", "voice": "fable", "greeting": "from file"}
    cfg_path = client_config_dir / "clients" / cid / "config.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps(file_cfg), encoding="utf-8")
    db_cfg = {"client_id": cid, "business_name": "DB Spa", "voice": "nova", "greeting": "from database"}

    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(main, "db_tenant_get_business_config", lambda c: db_cfg if c == cid else None)

    raw = main._read_raw_client_config(cid)
    assert raw is not None
    assert raw["voice"] == "nova"
    assert raw["greeting"] == "from database"


def test_save_raw_client_config_writes_db_and_file(client_config_dir, monkeypatch):
    cid = "save-test"
    stored = {}

    def fake_set(client_id, config):
        stored[client_id] = dict(config)
        return True

    monkeypatch.setattr("runtime.USE_DB", True)
    monkeypatch.setattr(main, "db_tenant_set_business_config", fake_set)

    data = main._default_client_config_data(cid, "free")
    data["voice"] = "shimmer"
    data["greeting"] = "Hello from save"
    main.save_raw_client_config(cid, data)

    assert stored[cid]["voice"] == "shimmer"
    file_path = client_config_dir / "clients" / cid / "config.json"
    assert file_path.exists()
    on_disk = json.loads(file_path.read_text(encoding="utf-8"))
    assert on_disk["greeting"] == "Hello from save"


def test_greeting_cache_key_uses_resolved_spoken_text(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {
            "name": "",
            "receptionist_name": "Aria",
            "greeting": "Thank you for calling {business_name}. I am {receptionist_name}.",
            "voice": "onyx",
            "speed": 1.25,
        },
    )
    monkeypatch.setattr(
        main,
        "_tenant_for_call_recording",
        lambda: {"name": "From Admin Tenant", "client_id": "ands-test"},
    )
    monkeypatch.setattr(main, "_call_recording_enabled_for_tenant", lambda _t: False)
    key = main._greeting_audio_cache_key("ands-test")
    assert key[0] == "ands-test"
    assert "From Admin Tenant" in key[1]
    assert "Aria" in key[1]
    assert key[2] == "onyx"
    assert key[3] == 1.25
