"""Reading a service menu out of a spreadsheet.

Built for salons migrating off another booking system — Zenoti exports everything
except appointments — where retyping fifty services by hand is the difference
between onboarding in minutes and not bothering.
"""

from __future__ import annotations

import io

import pytest

import service_import


def _xlsx(sheets: dict[str, list[list]]) -> bytes:
    """Build an in-memory workbook. {sheet_name: [[row], [row]]}"""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- Header and column detection ----------------------------------------------


def test_reads_a_plain_service_sheet():
    data = _xlsx({
        "Sheet1": [
            ["ServiceName", "Price", "Duration"],
            ["Haircut", 28, 30],
            ["Color", 75, 90],
        ]
    })
    out = service_import.parse_service_spreadsheet(data, "svc.xlsx")
    assert [s["name"] for s in out["services"]] == ["Haircut", "Color"]
    assert out["services"][0]["price"] == 28.0
    assert out["services"][1]["duration_minutes"] == 90


def test_header_can_be_below_junk_rows():
    """Real exports carry a title and blank rows above the header."""
    data = _xlsx({
        "Sheet1": [
            ["My Salon — service export"],
            [],
            ["Service Name", "Price", "Service time (in minutes)"],
            ["Haircut", "$28.00", "30"],
        ]
    })
    out = service_import.parse_service_spreadsheet(data, "svc.xlsx")
    assert [s["name"] for s in out["services"]] == ["Haircut"]
    assert out["services"][0]["price"] == 28.0


def test_missing_name_column_is_reported_not_guessed():
    data = _xlsx({"Sheet1": [["Price", "Duration"], [28, 30]]})
    out = service_import.parse_service_spreadsheet(data, "svc.xlsx")
    assert out["services"] == []
    assert any("service-name" in w.lower() or "service name" in w.lower() for w in out["warnings"])


def test_picks_the_richest_sheet_not_the_first_match():
    """A workbook usually has several tabs. A descriptions tab has a name-ish column
    too, so first-match picks prose instead of the actual catalogue."""
    data = _xlsx({
        "Service tree": [["Service requested", "Service Description"], ["Haircut", "A cut"]],
        "Services": [["ServiceName", "Service time (in minutes)", "Category"],
                     ["Shampoo & Haircut", 30, "Haircut Services"]],
    })
    out = service_import.parse_service_spreadsheet(data, "book.xlsx")
    assert out["sheet"] == "Services"
    assert [s["name"] for s in out["services"]] == ["Shampoo & Haircut"]


def test_an_explicit_sheet_wins():
    data = _xlsx({
        "A": [["ServiceName", "Duration"], ["From A", 30]],
        "B": [["ServiceName", "Duration"], ["From B", 30]],
    })
    out = service_import.parse_service_spreadsheet(data, "b.xlsx", sheet="B")
    assert [s["name"] for s in out["services"]] == ["From B"]


# --- Row handling -------------------------------------------------------------


def test_blank_and_null_names_are_skipped_not_stringified():
    """str(None) is "None", which is truthy — it would import a service called None."""
    data = _xlsx({
        "Sheet1": [["ServiceName", "Duration"], ["Haircut", 30], [None, 30], ["   ", 30]]
    })
    out = service_import.parse_service_spreadsheet(data, "svc.xlsx")
    assert [s["name"] for s in out["services"]] == ["Haircut"]
    assert not any(s["name"] == "None" for s in out["services"])
    assert any("skipped" in w for w in out["warnings"])


def test_prices_parse_from_messy_cells():
    data = _xlsx({
        "Sheet1": [["ServiceName", "Price", "Duration"],
                   ["A", "$28.00", 30], ["B", "1,250.50", 30], ["C", "free", 30]]
    })
    prices = [s["price"] for s in service_import.parse_service_spreadsheet(data, "s.xlsx")["services"]]
    assert prices == [28.0, 1250.5, 0.0]


def test_no_prices_produces_a_warning():
    """Their export often has durations but no prices, and the AI can't quote without
    them — say so rather than silently importing a priceless menu."""
    data = _xlsx({"Sheet1": [["ServiceName", "Duration"], ["Haircut", 30]]})
    out = service_import.parse_service_spreadsheet(data, "s.xlsx")
    assert any("price" in w.lower() for w in out["warnings"])


def test_row_cap_is_enforced():
    rows = [["ServiceName", "Duration"]] + [[f"S{i}", 30] for i in range(service_import.MAX_ROWS + 20)]
    out = service_import.parse_service_spreadsheet(_xlsx({"S": rows}), "s.xlsx")
    assert len(out["services"]) == service_import.MAX_ROWS
    assert any(str(service_import.MAX_ROWS) in w for w in out["warnings"])


# --- Add-on detection ---------------------------------------------------------


@pytest.mark.parametrize(
    "name,duration",
    [
        ("Hot tool Add-on", 20),
        ("Master Stylist 5", 0),
        ("Master Stylist 10", 0),
        ("Long Length", 0),
        ("Extra Long Length", 0),
        ("Medium Length and/or High Density", 0),
        ("Basic Conditioner", 0),
        ("Specialty Conditioner", 10),
        ("Additional Color", 0),
    ],
)
def test_addons_are_detected(name, duration):
    """From the real HairMasters catalogue — these are all charges that attach to a
    service, never appointments in their own right."""
    assert service_import._looks_like_addon(name, duration, "") is True


@pytest.mark.parametrize(
    "name,duration",
    [("Shampoo & Haircut", 30), ("Full Highlight", 120), ("Color", 90), ("Waxing 1 area", 15)],
)
def test_real_services_are_not_flagged_as_addons(name, duration):
    assert service_import._looks_like_addon(name, duration, "") is False


# --- Bad input ----------------------------------------------------------------


def test_garbage_file_degrades_to_a_message():
    out = service_import.parse_service_spreadsheet(b"not a spreadsheet at all", "x.xlsx")
    assert out["services"] == []
    assert out["warnings"]


def test_empty_file():
    out = service_import.parse_service_spreadsheet(b"", "x.xlsx")
    assert out["services"] == []
    assert out["warnings"]


def test_oversized_file_is_refused():
    out = service_import.parse_service_spreadsheet(b"x" * (service_import.MAX_BYTES + 1), "x.xlsx")
    assert out["services"] == []
    assert any("large" in w.lower() for w in out["warnings"])


# --- Suggesting which services an add-on belongs with -------------------------
# The keyword pass can tell "Master Stylist 10" is a charge; only the prose says it's
# for chemical services. The model reads that, then everything it returns is checked
# against the real lists before it can reach a config.

_SERVICES = [
    {"name": "Shampoo & Haircut", "is_addon": False},
    {"name": "Full Style", "is_addon": False},
    {"name": "All-over color", "is_addon": False},
    {"name": "Master Stylist 5", "is_addon": True},
    {"name": "Master Stylist 10", "is_addon": True},
]


def _stub_llm(monkeypatch, payload):
    import json as _json

    text = payload if isinstance(payload, str) else _json.dumps(payload)

    class _Fake:
        @staticmethod
        def chat(**kw):
            return text

    monkeypatch.setitem(__import__("sys").modules, "llm_provider", _Fake)


def test_suggests_links_from_the_notes(monkeypatch):
    _stub_llm(monkeypatch, {"links": [
        {"addon": "Master Stylist 5", "services": ["Shampoo & Haircut", "Full Style"]},
        {"addon": "Master Stylist 10", "services": ["All-over color"]},
    ]})
    out = service_import.suggest_addon_links(_SERVICES, "Master Stylist Charge for Haircuts")
    assert out["Master Stylist 5"] == ["Shampoo & Haircut", "Full Style"]
    assert out["Master Stylist 10"] == ["All-over color"]


def test_invented_service_names_are_rejected(monkeypatch):
    """A hallucinated service must never reach the config."""
    _stub_llm(monkeypatch, {"links": [
        {"addon": "Master Stylist 5", "services": ["Shampoo & Haircut", "Nonexistent Service"]},
    ]})
    out = service_import.suggest_addon_links(_SERVICES, "notes")
    assert out["Master Stylist 5"] == ["Shampoo & Haircut"]


def test_an_addon_with_no_valid_matches_is_dropped(monkeypatch):
    """Empty links would read as 'offer this with nothing' — better to leave the
    add-on available for everything."""
    _stub_llm(monkeypatch, {"links": [
        {"addon": "Master Stylist 5", "services": ["Only Invented Ones"]},
    ]})
    assert service_import.suggest_addon_links(_SERVICES, "notes") == {}


def test_unknown_addon_names_are_rejected(monkeypatch):
    _stub_llm(monkeypatch, {"links": [{"addon": "Ghost Charge", "services": ["Full Style"]}]})
    assert service_import.suggest_addon_links(_SERVICES, "notes") == {}


def test_matching_is_case_insensitive(monkeypatch):
    _stub_llm(monkeypatch, {"links": [
        {"addon": "master stylist 5", "services": ["SHAMPOO & HAIRCUT"]},
    ]})
    out = service_import.suggest_addon_links(_SERVICES, "notes")
    assert out["Master Stylist 5"] == ["Shampoo & Haircut"]


@pytest.mark.parametrize("reply", ["not json", "", '{"nope": 1}', "```json\n{bad}\n```"])
def test_bad_model_output_suggests_nothing(monkeypatch, reply):
    _stub_llm(monkeypatch, reply)
    assert service_import.suggest_addon_links(_SERVICES, "notes") == {}


def test_llm_failure_is_not_fatal(monkeypatch):
    """Suggestions are a convenience — an outage must not break the import."""

    class _Boom:
        @staticmethod
        def chat(**kw):
            raise RuntimeError("rate limited")

    monkeypatch.setitem(__import__("sys").modules, "llm_provider", _Boom)
    assert service_import.suggest_addon_links(_SERVICES, "notes") == {}


def test_no_notes_means_no_model_call(monkeypatch):
    """A single-sheet file has nothing to read, so don't spend a call on it."""

    class _Fail:
        @staticmethod
        def chat(**kw):
            raise AssertionError("should not be called")

    monkeypatch.setitem(__import__("sys").modules, "llm_provider", _Fail)
    assert service_import.suggest_addon_links(_SERVICES, "") == {}
    assert service_import.suggest_addon_links([], "some notes") == {}


# --- Unfamiliar layouts: the model locates, Python still reads ----------------
# The alias list only recognises headers we thought of. A salon exporting from
# software we've never seen labels the column something else entirely, and that must
# not be a dead end. The model only says WHERE to look — every index it returns is
# range-checked, and the rows themselves are always read by Python.


def _layout_llm(monkeypatch, payload, calls=None):
    import json as _json

    text = payload if isinstance(payload, str) else _json.dumps(payload)

    class _Fake:
        @staticmethod
        def chat(**kw):
            if calls is not None:
                calls.append(kw)
            return text

    monkeypatch.setitem(__import__("sys").modules, "llm_provider", _Fake)


_ALIEN = {
    "Tab1": [
        ["Treatment", "Mins", "Fee"],
        ["Scalp massage", 20, "35.00"],
        ["Beard sculpt", 45, "60.00"],
    ]
}


def test_an_unrecognised_header_falls_back_to_the_model(monkeypatch):
    """"Treatment"/"Mins"/"Fee" match none of our aliases."""
    assert service_import._find_header(_ALIEN["Tab1"])[0] == -1, "precondition: aliases miss"
    _layout_llm(monkeypatch, {
        "sheet": "Tab1", "header_row": 0,
        "columns": {"name": 0, "duration": 1, "price": 2, "category": None, "code": None},
    })
    out = service_import.parse_service_spreadsheet(_xlsx(_ALIEN), "alien.xlsx")
    assert [s["name"] for s in out["services"]] == ["Scalp massage", "Beard sculpt"]
    assert out["services"][0]["duration_minutes"] == 20
    assert out["services"][1]["price"] == 60.0
    assert any("wasn't one we recognised" in w for w in out["warnings"])


def test_a_sheet_with_no_header_row_at_all(monkeypatch):
    """header_row -1 means the data starts immediately."""
    _layout_llm(monkeypatch, {
        "sheet": "S", "header_row": -1, "columns": {"name": 0, "duration": 1},
    })
    out = service_import.parse_service_spreadsheet(
        _xlsx({"S": [["Scalp massage", 20], ["Beard sculpt", 45]]}), "x.xlsx"
    )
    assert [s["name"] for s in out["services"]] == ["Scalp massage", "Beard sculpt"]


def test_a_recognised_file_never_costs_a_layout_call(monkeypatch):
    """The deterministic pass is exact and free — the model is a fallback, not a step."""

    class _Fail:
        @staticmethod
        def chat(**kw):
            raise AssertionError("should not be called")

    monkeypatch.setitem(__import__("sys").modules, "llm_provider", _Fail)
    out = service_import.parse_service_spreadsheet(
        _xlsx({"S": [["ServiceName", "Duration"], ["Haircut", 30]]}), "s.xlsx"
    )
    assert [s["name"] for s in out["services"]] == ["Haircut"]
    assert not any("recognised" in w for w in out["warnings"])


@pytest.mark.parametrize(
    "payload",
    [
        {"sheet": "Nonexistent", "header_row": 0, "columns": {"name": 0}},   # invented sheet
        {"sheet": "Tab1", "header_row": 0, "columns": {"name": 99}},          # out of range
        {"sheet": "Tab1", "header_row": 0, "columns": {"name": -1}},          # negative
        {"sheet": "Tab1", "header_row": 0, "columns": {"price": 2}},          # no name column
        {"sheet": "Tab1", "header_row": 0, "columns": "nope"},                # wrong shape
        {"sheet": "Tab1", "header_row": 0},                                   # no columns
        "not json at all",
        "",
    ],
)
def test_a_bad_layout_answer_is_refused_not_used(monkeypatch, payload):
    """A wrong sheet or a made-up index must degrade to the normal 'couldn't find it'
    message, never to services read out of the wrong column."""
    _layout_llm(monkeypatch, payload)
    # Two sheets, so a missing/invented sheet name can't be resolved by being the only one.
    out = service_import.parse_service_spreadsheet(
        _xlsx({**_ALIEN, "Other": [["a", "b"], ["c", "d"]]}), "alien.xlsx"
    )
    assert out["services"] == []
    assert any("Couldn't find a service list" in w for w in out["warnings"])


def test_a_boolean_column_index_is_refused(monkeypatch):
    """bool is an int subclass — True would silently read as column 1."""
    _layout_llm(monkeypatch, {"sheet": "Tab1", "header_row": 0, "columns": {"name": True}})
    out = service_import.parse_service_spreadsheet(
        _xlsx({**_ALIEN, "Other": [["a"], ["c"]]}), "alien.xlsx"
    )
    assert out["services"] == []


def test_a_layout_outage_is_not_fatal(monkeypatch):
    class _Boom:
        @staticmethod
        def chat(**kw):
            raise RuntimeError("rate limited")

    monkeypatch.setitem(__import__("sys").modules, "llm_provider", _Boom)
    out = service_import.parse_service_spreadsheet(_xlsx(_ALIEN), "alien.xlsx")
    assert out["services"] == []
    assert out["warnings"]


def test_the_preview_carries_indexes_for_every_sheet():
    """The model answers in column indexes, so it has to see them."""
    text = service_import._preview_for_model(
        {"Tab1": _ALIEN["Tab1"], "Two": [["x"]]}
    )
    assert "SHEET Tab1" in text and "SHEET Two" in text
    assert "[0]=Treatment" in text and "[1]=Mins" in text
    assert "row 0:" in text


def test_the_preview_is_bounded():
    """A 5,000-row sheet must not become a 5,000-row prompt."""
    big = {"S": [[f"c{j}" for j in range(40)] for _ in range(500)]}
    text = service_import._preview_for_model(big)
    assert text.count("row ") <= service_import._PREVIEW_ROWS
    assert "[12]=" not in text


def test_csv_is_accepted():
    csv = b"ServiceName,Price,Duration\nHaircut,28,30\nColor,75,90\n"
    out = service_import.parse_service_spreadsheet(csv, "services.csv")
    assert [s["name"] for s in out["services"]] == ["Haircut", "Color"]
    assert out["services"][0]["price"] == 28.0
