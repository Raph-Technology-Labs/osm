"""Header-driven CSV/Excel importer for the OSM Part schema.

Plain layout, same as the GCM/SCM importer: row 1 = headers, row 2+ = one
part per row. A single sheet, so a CSV carries everything an .xlsx does
except embedded images.

Defects support unlimited numbered instances, writing Part.defects:
    d1_name, d1_threshold, d1_notes, d2_name, ...
        -> { "rust": { "conf_thresh": 0.7, "notes": "" } }

Measurement parameters do the same, writing Part.dimensions:
    p1_name, p1_nominal, p1_min, p1_max, p1_unit, p1_cal, p1_notes, p2_name, ...
        -> { "diameter_mm": { "nominal": 25.0, "upper_limit": 26.0,
                              "lower_limit": 24.0, "unit": "mm",
                              "calibration_factor": 1.002,
                              "notes": "shank diameter" } }

The parameter NAME is a cell value, not part of the header. OSM's
Part.defects and Part.dimensions are keyed by free-form names the pipeline
emits, so they cannot be baked into fixed column headers the way SCM's
fixed families (length1, od1_max) are.

Parsing is header-driven and never touches the database. The caller
resolves categories and persists.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import openpyxl
    from openpyxl.comments import Comment
    from openpyxl.styles import Font, PatternFill
except ImportError:  # pragma: no cover
    openpyxl = None

try:
    from openpyxl_image_loader import SheetImageLoader
except ImportError:  # pragma: no cover
    SheetImageLoader = None


PARTS_SHEET = "Parts"
MAX_PART_CODE_LEN = 50

FIXED_COLUMNS = ["part_code", "part_name", "category_name", "part_weight", "notes", "image"]

# d1_name, d1_threshold, d1_notes, d2_name, ... — instance number unbounded
_DEFECT_RE = re.compile(r"^d(\d+)_(name|threshold|notes)$")

# p1_name, p1_nominal, p1_min, p1_max, p1_unit, p1_cal, p1_notes, ... — unbounded
_PARAM_RE = re.compile(r"^p(\d+)_(name|nominal|min|max|unit|cal|notes)$")

HEADER_SYNONYMS: dict[str, list[str]] = {
    "part_code": ["code", "part code", "item", "item code", "sku"],
    "part_name": ["name", "part name", "description", "product name"],
    "category_name": ["category", "category name", "group", "family"],
    "part_weight": ["weight", "weight_g", "part weight"],
    "notes": ["note", "remarks", "comment", "comments"],
    "image": ["img", "picture", "photo", "image_url"],
}

FIXED_COLUMN_HELP = {
    "part_code": "REQUIRED. Unique identifier for this part (e.g. BOLT-M8-40).\n"
                 "Rows whose part_code already exists are skipped on upload.",
    "part_name": "Display name of the part. Falls back to part_code if left blank.",
    "category_name": "Groups this part under a category. Auto-created if new.",
    "part_weight": "Weight of the part, in grams. A single fixed number.",
    "notes": "Free text about the part itself.",
    "image": "Optional. Paste a picture into this cell, or leave blank.",
    "d1_name": "Name of the first defect to check for — must match the\n"
               "detection model's class name exactly (e.g. rust, crack).\n"
               "Add more defects with d3_name, d4_name, ... columns.",
    "d1_threshold": "Confidence threshold for d1, between 0 and 1. Optional.",
    "d1_notes": "Free text about this defect on this part. Optional.",
    "p1_name": "Name of the first measurement parameter — must match what the\n"
               "measurement step emits (e.g. diameter_mm).\n"
               "Add more parameters with p3_name, p4_name, ... columns.",
    "p1_nominal": "Target value for p1.",
    "p1_min": "Lower limit for p1. Set at least one of min/max, or the\n"
              "parameter is recorded but can never fail.",
    "p1_max": "Upper limit for p1.",
    "p1_unit": "Unit for p1 (mm, cm, um, deg, mm2). Optional.",
    "p1_cal": "Calibration factor for p1 — the raw measurement is multiplied\n"
              "by this before it is compared against min/max.\n"
              "Leave blank for 1.0 (no correction).",
    "p1_notes": "Free text about this parameter. Optional.",
}


# ─────────────────────────────────────────────────────────────────
# Row containers
# ─────────────────────────────────────────────────────────────────
@dataclass
class PartRow:
    """One parsed part, with its parameter dicts already in Part-column shape."""

    part_code: str
    part_name: Optional[str] = None
    category_name: Optional[str] = None
    part_weight: Optional[float] = None
    notes: Optional[str] = None
    image: Optional[bytes] = None
    dimensions: Optional[dict[str, Any]] = field(default=None)
    defects: Optional[dict[str, Any]] = field(default=None)


@dataclass
class ParseResult:
    rows: list[PartRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Header handling
# ─────────────────────────────────────────────────────────────────
def _clean(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")


def _build_header_map(columns) -> dict[Any, str]:
    """Fixed headers map to their canonical name via synonyms. Anything else
    passes through cleaned, so 'D1_Name' -> 'd1_name' and 'P2_Max' ->
    'p2_max', ready for the instance regexes below."""
    lookup: dict[str, str] = {}
    for canonical, spellings in HEADER_SYNONYMS.items():
        for s in [canonical, *spellings]:
            lookup[_clean(s)] = canonical
    return {col: lookup.get(_clean(col), _clean(col)) for col in columns}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _to_float(value: Any) -> Optional[float]:
    text = _cell(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"'{text}' is not a number")


# ─────────────────────────────────────────────────────────────────
# Instance extraction
# ─────────────────────────────────────────────────────────────────
def _extract_defects(rec: dict, code: str, errors: list[str]) -> Optional[dict]:
    """d1_* / d2_* / ... -> { <name>: { conf_thresh, notes } }

    Keyed by the NAME the admin typed, since that is what Part.defects uses.
    A slot with values but no name is dropped — there is nothing to key it
    by, so it is reported rather than silently ignored.
    """
    staged: dict[str, dict] = {}

    for key, raw in rec.items():
        m = _DEFECT_RE.match(key)
        if not m:
            continue
        idx, suffix = m.group(1), m.group(2)
        entry = staged.setdefault(idx, {})
        if suffix == "threshold":
            try:
                entry["conf_thresh"] = _to_float(raw)
            except ValueError as e:
                errors.append(f"{code}: d{idx}_threshold {e}")
        else:
            entry[suffix] = _cell(raw)

    out: dict[str, Any] = {}
    for idx in sorted(staged, key=int):
        entry = staged[idx]
        name = entry.get("name", "")
        if not name:
            if entry.get("conf_thresh") is not None or entry.get("notes"):
                errors.append(f"{code}: d{idx} has values but no name — skipped")
            continue

        conf = entry.get("conf_thresh")
        if conf is not None and not (0.0 <= conf <= 1.0):
            errors.append(f"{code}: {name} threshold must be between 0 and 1 — skipped")
            continue

        if name in out:
            errors.append(f"{code}: defect '{name}' appears twice — the later one wins")

        out[name] = {
            "conf_thresh": conf,
            "notes": entry.get("notes", ""),
        }

    return out or None


def _extract_dimensions(rec: dict, code: str, errors: list[str]) -> Optional[dict]:
    """p1_* / p2_* / ... ->
    { <name>: { nominal, upper_limit, lower_limit, unit,
                calibration_factor, notes } }
    """
    staged: dict[str, dict] = {}

    for key, raw in rec.items():
        m = _PARAM_RE.match(key)
        if not m:
            continue
        idx, suffix = m.group(1), m.group(2)
        entry = staged.setdefault(idx, {})
        if suffix in ("name", "unit", "notes"):
            entry[suffix] = _cell(raw)
        else:
            try:
                entry[suffix] = _to_float(raw)
            except ValueError as e:
                errors.append(f"{code}: p{idx}_{suffix} {e}")

    out: dict[str, Any] = {}
    for idx in sorted(staged, key=int):
        entry = staged[idx]
        name = entry.get("name", "")
        nominal, lower, upper = entry.get("nominal"), entry.get("min"), entry.get("max")
        cal = entry.get("cal")

        if not name:
            if any(v is not None for v in (nominal, lower, upper, cal)):
                errors.append(f"{code}: p{idx} has values but no name — skipped")
            continue

        ctx = f"{code}: {name}"
        # A zero or negative factor would silently zero out or invert every
        # measurement for this parameter.
        if cal is not None and cal <= 0:
            errors.append(f"{ctx}: calibration factor must be greater than 0 — skipped")
            continue
        if lower is None and upper is None:
            errors.append(f"{ctx} has no limits — it can never fail. Skipped.")
            continue
        if lower is not None and upper is not None and lower > upper:
            errors.append(f"{ctx}: min is above max — skipped")
            continue
        if nominal is not None and lower is not None and nominal < lower:
            errors.append(f"{ctx}: nominal is below min — skipped")
            continue
        if nominal is not None and upper is not None and nominal > upper:
            errors.append(f"{ctx}: nominal is above max — skipped")
            continue

        if name in out:
            errors.append(f"{code}: parameter '{name}' appears twice — the later one wins")

        out[name] = {
            "nominal": nominal,
            "upper_limit": upper,
            "lower_limit": lower,
            "unit": entry.get("unit", ""),
            "calibration_factor": cal,
            "notes": entry.get("notes", ""),
        }

    return out or None


def _row_to_part(rec: dict, line_no: int, errors: list[str]) -> Optional[PartRow]:
    code = _cell(rec.get("part_code"))
    if not code:
        if any(_cell(v) for v in rec.values()):
            errors.append(f"Row {line_no}: missing part_code")
        return None
    if len(code) > MAX_PART_CODE_LEN:
        errors.append(f"{code}: part_code exceeds {MAX_PART_CODE_LEN} characters")
        return None

    try:
        weight = _to_float(rec.get("part_weight"))
    except ValueError as e:
        errors.append(f"{code}: part_weight {e}")
        weight = None

    category = _cell(rec.get("category_name"))
    image = rec.get("image")

    return PartRow(
        part_code=code,
        part_name=_cell(rec.get("part_name")) or code,
        category_name=category.upper() if category else None,
        part_weight=weight,
        notes=_cell(rec.get("notes")) or None,
        image=image if isinstance(image, bytes) else None,
        defects=_extract_defects(rec, code, errors),
        dimensions=_extract_dimensions(rec, code, errors),
    )


def _dedupe(rows: list[PartRow], errors: list[str]) -> list[PartRow]:
    seen: set[str] = set()
    out: list[PartRow] = []
    for row in rows:
        if row.part_code in seen:
            errors.append(f"{row.part_code}: appears more than once in the file")
            continue
        seen.add(row.part_code)
        out.append(row)
    return out


# ─────────────────────────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────────────────────────
class PartCsvImporter:
    """Same columns as the workbook — a single sheet means CSV loses nothing
    except embedded images."""

    def __init__(self, file):
        raw = file.read() if hasattr(file, "read") else file
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig", errors="replace")
        self._reader = csv.DictReader(io.StringIO(raw))

    def process(self) -> ParseResult:
        errors: list[str] = []
        header_map = _build_header_map(self._reader.fieldnames or [])

        rows: list[PartRow] = []
        for line_no, raw in enumerate(self._reader, start=2):
            rec = {header_map.get(k, _clean(k)): v for k, v in raw.items()}
            part = _row_to_part(rec, line_no, errors)
            if part:
                rows.append(part)

        return ParseResult(rows=_dedupe(rows, errors), errors=errors)


# ─────────────────────────────────────────────────────────────────
# Excel
# ─────────────────────────────────────────────────────────────────
class PartExcelImporter:
    """Plain layout: row 1 = headers, row 2+ = part data."""

    def __init__(self, file: io.BytesIO):
        if openpyxl is None:
            raise RuntimeError("openpyxl is required for Excel import")
        # read_only is off: SheetImageLoader needs the full workbook model.
        self.wb = openpyxl.load_workbook(file, data_only=True)
        self.sheet = (
            self.wb[PARTS_SHEET] if PARTS_SHEET in self.wb.sheetnames else self.wb.active
        )
        self.image_loader = SheetImageLoader(self.sheet) if SheetImageLoader else None

        raw_headers = [c.value for c in next(self.sheet.iter_rows(min_row=1, max_row=1))]
        header_map = _build_header_map(raw_headers)
        self.col_names = {i: header_map.get(h, _clean(h)) for i, h in enumerate(raw_headers)}
        self.name_to_idx = {v: k for k, v in self.col_names.items()}

    def _image_from_cell(self, row_number: int) -> Optional[bytes]:
        """Part.image holds the image file's own bytes, so this writes PNG
        bytes directly -- no base64 wrapper."""
        if self.image_loader is None or "image" not in self.name_to_idx:
            return None
        col = openpyxl.utils.get_column_letter(self.name_to_idx["image"] + 1)
        cell = f"{col}{row_number}"
        try:
            if not self.image_loader.image_in(cell):
                return None
            img = self.image_loader.get(cell).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None

    def process(self) -> ParseResult:
        errors: list[str] = []
        rows: list[PartRow] = []

        for line_no, excel_row in enumerate(
            self.sheet.iter_rows(min_row=2, values_only=True), start=2
        ):
            rec = {
                self.col_names[i]: v
                for i, v in enumerate(excel_row)
                if i in self.col_names
            }
            if not any(_cell(v) for v in rec.values()):
                continue
            if not rec.get("image"):
                rec["image"] = self._image_from_cell(line_no)

            part = _row_to_part(rec, line_no, errors)
            if part:
                rows.append(part)

        if not rows and not errors:
            errors.append(f"No data rows found on the '{PARTS_SHEET}' sheet")

        return ParseResult(rows=_dedupe(rows, errors), errors=errors)


# ─────────────────────────────────────────────────────────────────
# Template
# ─────────────────────────────────────────────────────────────────
def _template_headers(defect_slots: int = 2, param_slots: int = 2) -> list[str]:
    headers = list(FIXED_COLUMNS)
    for n in range(1, defect_slots + 1):
        headers += [f"d{n}_name", f"d{n}_threshold", f"d{n}_notes"]
    for n in range(1, param_slots + 1):
        headers += [
            f"p{n}_name", f"p{n}_nominal", f"p{n}_min", f"p{n}_max",
            f"p{n}_unit", f"p{n}_cal", f"p{n}_notes",
        ]
    return headers


def _style_header(ws, headers: list[str]) -> None:
    header_font = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="B71C1C")
    for c in ws[1]:
        c.font = header_font
        c.fill = fill
    for i, col in enumerate(headers, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = max(
            14, len(col) + 2
        )


def _add_comments(ws, headers: list[str]) -> None:
    name_to_col = {name: i for i, name in enumerate(headers, 1)}
    for name, help_text in FIXED_COLUMN_HELP.items():
        if name in name_to_col:
            ws.cell(row=1, column=name_to_col[name]).comment = Comment(
                help_text, "Template Guide"
            )


def _add_instructions(wb) -> None:
    ws = wb.create_sheet("Instructions", 0)
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 86

    ws.append(["Bulk Upload Template"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append([None, "One row per part on the 'Parts' sheet. Fill in what applies "
                     "and leave the rest blank."])
    ws.append([])

    ws.append(["Fixed Columns"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=12)
    ws.append(["Column", "What it means"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="EFEFEF")
    for col, desc in [
        ("part_code", "REQUIRED. Unique ID for the part. Duplicates are skipped."),
        ("part_name", "Display name. Defaults to part_code if left blank."),
        ("category_name", "Groups the part under a category. Auto-created if new."),
        ("part_weight", "Weight in grams. One fixed number."),
        ("notes", "Free text about the part."),
        ("image", "Optional. Paste a picture into the cell."),
    ]:
        ws.append([col, desc])
    ws.append([])

    ws.append(["Defects"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=12)
    for line in [
        "One defect per numbered slot: d1_name, d1_threshold, d1_notes.",
        "The name must match the detection model's class name exactly (rust, crack, ...).",
        "d1_threshold is the confidence cut-off, 0 to 1. Optional.",
        "The template ships with two slots. For a third defect, add your own columns:",
        "    d3_name, d3_threshold, d3_notes — and so on. There is no limit.",
        "A slot with values but no name is skipped and reported.",
    ]:
        ws.append([None, line])
    ws.append([])

    ws.append(["Measurement Parameters"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=12)
    for line in [
        "One parameter per numbered slot: p1_name, p1_nominal, p1_min, p1_max,",
        "    p1_unit, p1_cal, p1_notes.",
        "The name must match what the measurement step emits (diameter_mm, ...).",
        "p1_min / p1_max become lower_limit / upper_limit on the part.",
        "p1_cal scales the raw measurement before it is compared against the",
        "    limits. Blank means 1.0 — no correction. It must be greater than 0.",
        "The template ships with two slots. For a third parameter, add your own columns:",
        "    p3_name, p3_nominal, p3_min, p3_max, p3_unit, p3_cal, p3_notes — no limit.",
        "Set at least one of min/max: a parameter with neither is recorded but can",
        "never fail, so it is skipped and reported rather than silently accepted.",
    ]:
        ws.append([None, line])


def build_template() -> io.BytesIO:
    """Returns an in-memory .xlsx. Nothing is written to disk, which avoids
    the whole class of bugs where a stale regenerated file gets served."""
    if openpyxl is None:
        raise RuntimeError("openpyxl is required to build the template")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = PARTS_SHEET

    headers = _template_headers()
    ws.append(headers)

    example = {
        "part_code": "BOLT-M8-40",
        "part_name": "Hex Bolt M8x40",
        "category_name": "Fasteners",
        "part_weight": 12.4,
        "notes": "reference part",
        "d1_name": "rust",
        "d1_threshold": 0.70,
        "d2_name": "scratch",
        "d2_threshold": 0.90,
        "d2_notes": "cosmetic only",
        "p1_name": "diameter_mm",
        "p1_nominal": 25.0,
        "p1_min": 24.0,
        "p1_max": 26.0,
        "p1_unit": "mm",
        "p1_cal": 1.002,
        "p1_notes": "shank diameter",
        "p2_name": "length_mm",
        "p2_nominal": 40.0,
        "p2_min": 39.5,
        "p2_max": 40.5,
        "p2_unit": "mm",
    }
    ws.append([example.get(h, "") for h in headers])

    second = {
        "part_code": "WASHER-M8",
        "part_name": "Flat Washer M8",
        "category_name": "Fasteners",
        "part_weight": 1.1,
        "p1_name": "outer_diameter_mm",
        "p1_nominal": 16.0,
        "p1_min": 15.7,
        "p1_max": 16.3,
        "p1_unit": "mm",
    }
    ws.append([second.get(h, "") for h in headers])

    ws.freeze_panes = "A2"
    _style_header(ws, headers)
    _add_comments(ws, headers)
    _add_instructions(wb)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf