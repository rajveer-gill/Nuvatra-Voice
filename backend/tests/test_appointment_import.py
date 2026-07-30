"""Pasted-appointment import (Zenoti bridge).

An LLM does the extraction, so these tests are mostly about NOT trusting it: bad
shapes, hallucinated times, and junk must degrade safely rather than reach the
calendar. The LLM call itself is always stubbed — no network in tests.
"""

from __future__ import annotations

import json

import pytest

import appointment_import as ai


def _stub_llm(monkeypatch, payload):
    """Make llm_provider.chat return `payload` (str passed through, dict as JSON)."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(ai.llm_provider, "chat", lambda **kw: text)


# --- Normalization ------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2:30 PM", "14:30"), ("14:00", "14:00"), ("9:05 AM", "09:05"),
        ("0900", "09:00"), ("12 AM", "00:00"), ("12 PM", "12:00"),
        ("", ""), ("soon", ""), ("25:00", ""), ("14:99", ""),
    ],
)
def test_time_normalization(raw, expected):
    assert ai._normalize_time(raw) == expected


def test_out_of_range_time_is_dropped_not_clamped():
    """A hallucinated "25:00" must drop the row, never become 23:59 or 01:00."""
    assert ai._normalize_time("25:00") == ""


@pytest.mark.parametrize(
    "raw,expected",
    [("2026-07-22", "2026-07-22"), ("7/22/2026", "2026-07-22"), ("7/22/26", "2026-07-22")],
)
def test_date_normalization(raw, expected):
    assert ai._normalize_date(raw) == expected


def test_bare_date_uses_the_pasted_day_year():
    assert ai._normalize_date("7/22", fallback="2026-01-15") == "2026-07-22"


def test_missing_date_falls_back_to_the_pasted_day():
    """A Zenoti queue view is one day and often shows no date at all."""
    assert ai._normalize_date("", fallback="2026-07-22") == "2026-07-22"


@pytest.mark.parametrize("raw", ["first available", "First Available", "any", "N/A", "-"])
def test_first_available_means_no_stylist(raw):
    assert ai._clean_stylist(raw) == ""


def test_named_stylist_is_kept_and_whitespace_collapsed():
    assert ai._clean_stylist("  Jamie   B ") == "Jamie B"


# --- Parsing ------------------------------------------------------------------


def test_happy_path_extraction(monkeypatch):
    _stub_llm(monkeypatch, {"appointments": [
        {"customer_name": "Shannon", "service": "Shampoo & Haircut", "stylist": "Jamie",
         "time": "2:30 PM", "date": "", "is_request": True, "notes": ""},
    ]})
    out = ai.parse_pasted_appointments("(queue text)", default_date="2026-07-22")
    assert out["warnings"] == []
    row = out["appointments"][0]
    assert row["customer_name"] == "Shannon"
    assert row["time"] == "14:30"
    assert row["date"] == "2026-07-22"  # filled from the pasted day
    assert row["is_request"] is True


def test_rows_without_a_name_or_time_are_skipped_with_a_warning(monkeypatch):
    _stub_llm(monkeypatch, {"appointments": [
        {"customer_name": "Real Guest", "time": "10:00"},
        {"customer_name": "", "time": "11:00"},          # header/blank row
        {"customer_name": "No Time", "time": "whenever"},  # unreadable
    ]})
    out = ai.parse_pasted_appointments("x", default_date="2026-07-22")
    assert len(out["appointments"]) == 1
    assert any("skipped" in w for w in out["warnings"])


def test_empty_paste_is_handled():
    out = ai.parse_pasted_appointments("   ")
    assert out["appointments"] == []
    assert out["warnings"]


def test_llm_failure_degrades_safely(monkeypatch):
    def boom(**kw):
        raise RuntimeError("provider down")
    monkeypatch.setattr(ai.llm_provider, "chat", boom)
    out = ai.parse_pasted_appointments("some text")
    assert out["appointments"] == []
    assert out["warnings"]  # user-facing message, not a crash


@pytest.mark.parametrize("reply", [
    "I couldn't find any appointments, sorry!",   # prose instead of JSON
    "{not json at all",
    "",
    '{"something_else": []}',
])
def test_bad_model_output_never_raises(monkeypatch, reply):
    _stub_llm(monkeypatch, reply)
    out = ai.parse_pasted_appointments("x", default_date="2026-07-22")
    assert out["appointments"] == []
    assert out["warnings"]


def test_json_inside_a_code_fence_is_read(monkeypatch):
    """Models often wrap JSON in ```json fences despite instructions."""
    _stub_llm(monkeypatch, '```json\n{"appointments": [{"customer_name": "A", "time": "09:00"}]}\n```')
    out = ai.parse_pasted_appointments("x", default_date="2026-07-22")
    assert len(out["appointments"]) == 1


def test_non_dict_rows_are_ignored(monkeypatch):
    _stub_llm(monkeypatch, {"appointments": ["just a string", 42, None,
                                             {"customer_name": "Good", "time": "13:00"}]})
    out = ai.parse_pasted_appointments("x", default_date="2026-07-22")
    assert [r["customer_name"] for r in out["appointments"]] == ["Good"]


def test_row_cap_is_enforced(monkeypatch):
    many = [{"customer_name": f"G{i}", "time": "10:00"} for i in range(ai.MAX_ROWS + 25)]
    _stub_llm(monkeypatch, {"appointments": many})
    out = ai.parse_pasted_appointments("x", default_date="2026-07-22")
    assert len(out["appointments"]) == ai.MAX_ROWS
    assert any(str(ai.MAX_ROWS) in w for w in out["warnings"])


def test_oversized_paste_is_truncated_with_a_warning(monkeypatch):
    _stub_llm(monkeypatch, {"appointments": []})
    out = ai.parse_pasted_appointments("x" * (ai.MAX_PASTE_CHARS + 500), default_date="2026-07-22")
    assert any("characters" in w for w in out["warnings"])


# --- Idempotency key ----------------------------------------------------------


def test_same_guest_same_slot_is_the_same_appointment():
    a = {"date": "2026-07-22", "time": "14:30", "customer_name": "Shannon M."}
    b = {"date": "2026-07-22", "time": "14:30", "customer_name": "shannon m"}
    assert ai.import_key(a) == ai.import_key(b), "re-pasting must not duplicate"


def test_different_slot_is_a_different_appointment():
    base = {"date": "2026-07-22", "time": "14:30", "customer_name": "Shannon"}
    assert ai.import_key(base) != ai.import_key({**base, "time": "15:00"})
    assert ai.import_key(base) != ai.import_key({**base, "date": "2026-07-23"})
    assert ai.import_key(base) != ai.import_key({**base, "customer_name": "Dana"})


# --- Commit-side validation ---------------------------------------------------
# The preview rows are hand-editable in the UI and /commit accepts arbitrary client
# JSON, so it must re-validate rather than trust what it's handed.


def _commit(monkeypatch, rows, existing=None):
    """Call the commit endpoint's logic with the DB stubbed. Returns (result, inserted)."""
    from routers import appointments as ap

    inserted = []
    monkeypatch.setattr(ap, "_require_external_booking", lambda tenant: "shop-1")
    monkeypatch.setattr(ap.runtime, "USE_DB", True)
    monkeypatch.setattr(
        ap.database, "db_appointments_get_all", lambda client_id=None: existing or []
    )
    monkeypatch.setattr(
        ap.database, "db_appointments_insert", lambda d: (inserted.append(d), {"id": 1})[1]
    )
    monkeypatch.setattr(ap.database, "db_appointments_update", lambda *a, **k: {"id": 1})
    req = ap.ImportCommitRequest(appointments=rows)
    return ap.import_appointments_commit(req, tenant={"client_id": "shop-1"}), inserted


def _row(**over):
    base = {
        "customer_name": "Shannon",
        "service": "Haircut",
        "stylist": "",
        "date": "2026-07-22",
        "time": "14:30",
        "is_request": False,
        "notes": "",
    }
    base.update(over)
    return base


def test_commit_inserts_a_valid_row(monkeypatch):
    res, inserted = _commit(monkeypatch, [_row()])
    assert res["created"] == 1
    assert inserted[0]["date"] == "2026-07-22"
    assert inserted[0]["time"] == "14:30"
    assert inserted[0]["status"] == "confirmed"
    assert inserted[0]["source"] == "imported"


@pytest.mark.parametrize(
    "bad", [{"time": "25:00"}, {"time": "later"}, {"time": ""},
            {"date": "not-a-date"}, {"date": ""}, {"customer_name": "   "}],
)
def test_commit_rejects_a_bad_edited_row(monkeypatch, bad):
    """A hand-edited (or hand-crafted) bad value must not reach the calendar."""
    res, inserted = _commit(monkeypatch, [_row(**bad)])
    assert inserted == []
    assert res["created"] == 0
    assert res["invalid"] == 1


def test_commit_normalizes_an_edited_time(monkeypatch):
    """The UI sends HH:MM, but a direct caller might send '2:30 PM'."""
    res, inserted = _commit(monkeypatch, [_row(time="2:30 PM")])
    assert res["created"] == 1
    assert inserted[0]["time"] == "14:30"


def test_commit_updates_instead_of_duplicating(monkeypatch):
    """Re-importing a day the store already pasted must not create a second row."""
    existing = [{"id": 9, "date": "2026-07-22", "time": "14:30", "name": "Shannon"}]
    res, inserted = _commit(monkeypatch, [_row()], existing=existing)
    assert res["updated"] == 1
    assert res["created"] == 0
    assert inserted == []
