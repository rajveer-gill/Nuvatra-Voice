"""Read a service menu out of a spreadsheet.

Salons on another booking system can export their service list to Excel — Zenoti
can export everything except appointments — so this turns that file into our service
rows instead of making someone retype fifty of them by hand. At thirty-odd locations
that difference decides whether onboarding is feasible.

Deliberately forgiving about layout: the header row is found by looking for a
name-ish column rather than assuming row 1, and column names are matched loosely,
because every system labels these differently ("ServiceName", "Service Name",
"Service"). Anything it can't read is reported rather than guessed at — the caller
shows the rows for confirmation before they're saved.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any, Optional

logger = logging.getLogger("nuvatra")

MAX_ROWS = 500
MAX_BYTES = 5 * 1024 * 1024  # a service list is kilobytes; anything larger is a mistake

# Column header aliases, lowercased and stripped of non-letters for matching.
# Deliberately NOT "description" — a real export often has both a name column and a
# "Service Description" column, and matching the latter picks prose instead of names.
_NAME_KEYS = {"servicename", "name", "service", "servicerequested"}
_PRICE_KEYS = {"price", "cost", "amount", "rate", "listprice"}
_DURATION_KEYS = {"servicetime", "servicetimeinminutes", "duration", "durationminutes",
                  "time", "minutes", "length"}
_CATEGORY_KEYS = {"category", "subcategory", "servicecategory", "group", "type"}
_CODE_KEYS = {"servicecode", "code", "sku", "id"}


def _key(s: Any) -> str:
    return re.sub(r"[^a-z]", "", str(s or "").lower())


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return max(0.0, float(v))
    m = re.search(r"(\d+(?:\.\d+)?)", str(v).replace(",", ""))
    return max(0.0, float(m.group(1))) if m else 0.0


def _to_int(v: Any, default: int) -> int:
    if isinstance(v, (int, float)):
        n = int(v)
    else:
        m = re.search(r"(\d+)", str(v or ""))
        n = int(m.group(1)) if m else default
    return n


def _looks_like_addon(name: str, duration: int, category: str) -> bool:
    """Best-effort guess, shown as a pre-ticked box the user can correct.

    Add-ons betray themselves two ways: the name says so ("Hot tool Add-on",
    "Master Stylist 5", the length charges), or the row has no duration because it's
    a charge rather than a booking. Never authoritative — the preview is editable
    precisely because this is a heuristic.
    """
    n = name.lower()
    if any(w in n for w in ("add-on", "add on", "addon", "master stylist")):
        return True
    if any(w in n for w in ("length", "density")) and duration == 0:
        return True
    if "conditioner" in n and duration <= 10:
        return True
    if duration == 0 and any(w in n for w in ("additional", "charge", "upgrade")):
        return True
    return False


def _find_header(rows: list[list[Any]]) -> tuple[int, dict[str, int]]:
    """Locate the header row and map our fields to column indexes.

    Scans the first 20 rows rather than assuming row 1 — exports routinely carry a
    title or blank rows above the real header. Returns (-1, {}) when no row has
    something name-like in it.
    """
    for i, row in enumerate(rows[:20]):
        keys = [_key(c) for c in row]
        name_ix = next((j for j, k in enumerate(keys) if k in _NAME_KEYS), None)
        if name_ix is None:
            continue
        mapping = {"name": name_ix}
        for field, aliases in (
            ("price", _PRICE_KEYS),
            ("duration", _DURATION_KEYS),
            ("category", _CATEGORY_KEYS),
            ("code", _CODE_KEYS),
        ):
            ix = next((j for j, k in enumerate(keys) if k in aliases and j != name_ix), None)
            if ix is not None:
                mapping[field] = ix
        return i, mapping
    return -1, {}


def parse_service_spreadsheet(
    data: bytes, filename: str = "", sheet: Optional[str] = None
) -> dict:
    """Parse an .xlsx/.csv service list.

    Returns {"services": [...], "warnings": [...], "sheets": [...], "sheet": str}.
    Never raises for a bad file — it reports the problem so the UI can say what's
    wrong rather than 500ing.
    """
    warnings: list[str] = []
    if not data:
        return {"services": [], "warnings": ["The file was empty."], "sheets": [], "sheet": ""}
    if len(data) > MAX_BYTES:
        return {
            "services": [],
            "warnings": ["That file is too large — export just the service list."],
            "sheets": [],
            "sheet": "",
        }

    rows: list[list[Any]] = []
    sheets: list[str] = []
    chosen = ""
    name = (filename or "").lower()
    try:
        if name.endswith(".csv") or name.endswith(".txt"):
            import csv

            text = data.decode("utf-8-sig", errors="replace")
            rows = [list(r) for r in csv.reader(io.StringIO(text))]
        else:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
            sheets = list(wb.sheetnames)
            # Prefer the requested sheet, else the first one that actually parses —
            # a real export often has several tabs (services, staff, locations).
            if sheet and sheet in sheets:
                chosen = sheet
                rows = [list(r) for r in wb[chosen].iter_rows(values_only=True)]
            else:
                # Score every sheet and take the richest. A workbook usually has
                # several tabs, and the first one with a name-ish column is often the
                # wrong one — a descriptions tab beats the actual catalogue on a
                # first-match rule. Columns like duration and price are what identify
                # a real service list.
                best_score = -1
                for candidate in sheets:
                    candidate_rows = [
                        list(r) for r in wb[candidate].iter_rows(values_only=True)
                    ]
                    ix, cols = _find_header(candidate_rows)
                    if ix < 0:
                        continue
                    score = len(cols) + (2 if "duration" in cols else 0) + (
                        2 if "price" in cols else 0
                    )
                    if score > best_score:
                        best_score, rows, chosen = score, candidate_rows, candidate
                if not rows and sheets:
                    chosen = sheets[0]
                    rows = [list(r) for r in wb[chosen].iter_rows(values_only=True)]
    except Exception as e:
        logger.warning("service_import_read_failed file=%r err=%s", filename, e)
        return {
            "services": [],
            "warnings": ["Couldn't read that file. Please upload a .xlsx or .csv export."],
            "sheets": sheets,
            "sheet": chosen,
        }

    header_ix, cols = _find_header(rows)
    if header_ix < 0:
        return {
            "services": [],
            "warnings": [
                "Couldn't find a service-name column. The sheet needs a header row with "
                "something like 'Service Name'."
            ],
            "sheets": sheets,
            "sheet": chosen,
        }

    out: list[dict] = []
    skipped = 0
    for row in rows[header_ix + 1 :]:
        if len(out) >= MAX_ROWS:
            warnings.append(f"Only the first {MAX_ROWS} services were read.")
            break
        if not row:
            continue
        name_ix = cols["name"]
        raw_name = row[name_ix] if name_ix < len(row) else None
        # Guard the None explicitly: str(None) is "None", which is truthy and would
        # sail through as a service literally called "None".
        svc_name = re.sub(r"\s+", " ", str(raw_name).strip())[:200] if raw_name is not None else ""
        if not svc_name or _key(svc_name) in _NAME_KEYS:
            skipped += 1
            continue

        def cell(field: str):
            ix = cols.get(field)
            return row[ix] if ix is not None and ix < len(row) else None

        duration = _to_int(cell("duration"), 30)
        duration = max(0, min(duration, 480))
        category = str(cell("category") or "").strip()[:120]
        out.append(
            {
                "name": svc_name,
                "price": round(_to_float(cell("price")), 2),
                # 0 is meaningful here (an add-on charge with no time of its own), so
                # it's preserved; the UI floors it to 5 for anything actually bookable.
                "duration_minutes": duration,
                "category": category,
                "code": str(cell("code") or "").strip()[:64],
                "is_addon": _looks_like_addon(svc_name, duration, category),
            }
        )

    if skipped:
        warnings.append(f"{skipped} row(s) were skipped — no service name.")
    if out and not any(s["price"] for s in out):
        warnings.append(
            "No prices were found in this file — you can add them after importing, or "
            "the receptionist will say the shop confirms pricing when booking."
        )
    return {"services": out, "warnings": warnings, "sheets": sheets, "sheet": chosen}
