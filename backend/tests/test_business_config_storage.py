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

    monkeypatch.setattr(main, "USE_DB", True)
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

    monkeypatch.setattr(main, "USE_DB", True)
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


def test_greeting_cache_key_includes_voice(client_config_dir, monkeypatch):
    monkeypatch.setattr(
        main,
        "get_business_info",
        lambda: {
            "name": "Spa",
            "receptionist_name": "",
            "greeting": "Hi",
            "voice": "onyx",
            "speed": 1.25,
        },
    )
    monkeypatch.setattr(main, "_call_recording_enabled_for_tenant", lambda _t: False)
    monkeypatch.setattr(main, "_tenant_for_call_recording", lambda: None)
    key = main._greeting_audio_cache_key("test-spa")
    assert key[-2] == "onyx"
    assert key[-1] == 1.25
