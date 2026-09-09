"""Header-driven CSV/Excel importer for the OSM Part schema.

Layout -- a three-sheet workbook in long format:

    Parts:       part_code | part_name | category_name | part_weight | notes
    Dimensions:  part_code | param_name | nominal | lower_limit | upper_limit | unit | notes
    Defects:     part_code | class_name | conf_thresh | severity | notes

One row per parameter, joined back to its part by part_code. This differs
from the numbered-instance column scheme (length1, length1_max, d1_name)
used in the GCM/SCM importer: OSM's Part.dimensions and Part.defects are
keyed by free-form names the pipeline emits, so they cannot be flattened
into a fixed set of columns.

A CSV carries the Parts sheet only -- parameters need the workbook.

Parsing is header-driven and never touches the database. The caller
resolves categories and persists.
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None

try:
    from openpyxl_image_loader import SheetImageLoader
except ImportError:  # pragma: no cover
    SheetImageLoader = None


PARTS_SHEET = "Parts"
DIMENSIONS_SHEET = "Dimensions"
DEFECTS_SHEET = "Defects"

PARTS_COLUMNS = ["part_code", "part_name", "category_name", "part_weight", "notes"]
DIMENSIONS_COLUMNS = [
    "part_code", "param_name", "nominal", "lower_limit", "upper_limit", "unit", "notes",
]
DEFECTS_COLUMNS = ["part_code", "class_name", "conf_thresh", "severity", "notes"]

VALID_SEVERITIES = {"critical", "major", "minor"}
DEFAULT_SEVERITY = "critical"
MAX_PART_CODE_LEN = 50

HEADER_SYNONYMS: dict[str, list[str]] = {
    # Parts
    "part_code": ["code", "part code", "item", "item code", "sku"],
    "part_name": ["name", "part name", "description", "product name"],
    "category_name": ["category", "category name", "group", "family"],
    "part_weight": ["weight", "weight_g", "part weight"],
    "notes": ["note", "remarks", "comment", "comments"],
    "image": ["img", "picture", "photo"],
    # Dimensions
    "param_name": ["parameter", "parameter name", "dimension", "dimension name", "param"],
    "nominal": ["nominal value", "target", "nominal_mm"],
    "lower_limit": ["lower", "lsl", "min", "min_value", "lower limit", "lower tolerance"],
    "upper_limit": ["upper", "usl", "max", "max_value", "upper limit", "upper tolerance"],
    "unit": ["units", "uom"],
    # Defects
    "class_name": ["class", "defect", "defect name", "defect_name", "label"],
    "conf_thresh": [
        "confidence", "confidence threshold", "conf", "threshold", "confidence_threshold",
    ],
    "severity": ["level", "criticality"],
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
    """Map raw headers onto canonical names via the synonym table.

    Unknown headers pass through cleaned, so they simply never match a
    canonical column and are ignored rather than crashing the import.
    """
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
# Parameter assembly
# ─────────────────────────────────────────────────────────────────
def _dimension_entry(rec: dict, ctx: str) -> dict[str, Any]:
    try:
        nominal = _to_float(rec.get("nominal"))
        lower = _to_float(rec.get("lower_limit"))
        upper = _to_float(rec.get("upper_limit"))
    except ValueError as e:
        raise ValueError(f"{ctx}: {e}")

    if lower is not None and upper is not None and lower > upper:
        raise ValueError(f"{ctx}: lower_limit is above upper_limit")
    if nominal is not None and lower is not None and nominal < lower:
        raise ValueError(f"{ctx}: nominal is below lower_limit")
    if nominal is not None and upper is not None and nominal > upper:
        raise ValueError(f"{ctx}: nominal is above upper_limit")

    return {
        "nominal": nominal,
        "upper_limit": upper,
        "lower_limit": lower,
        "unit": _cell(rec.get("unit")),
        "notes": _cell(rec.get("notes")),
    }


def _defect_entry(rec: dict, ctx: str) -> dict[str, Any]:
    try:
        conf = _to_float(rec.get("conf_thresh"))
    except ValueError as e:
        raise ValueError(f"{ctx}: {e}")

    if conf is not None and not (0.0 <= conf <= 1.0):
        raise ValueError(f"{ctx}: conf_thresh must be between 0 and 1")

    severity = (_cell(rec.get("severity")) or DEFAULT_SEVERITY).lower()
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f"{ctx}: severity must be one of {', '.join(sorted(VALID_SEVERITIES))}"
        )

    return {
        "conf_thresh": conf,
        "severity": severity,
        "notes": _cell(rec.get("notes")),
    }


def _group_parameters(
    rows: list[tuple[int, dict]],
    key_column: str,
    build_entry,
    sheet_name: str,
    errors: list[str],
) -> dict[str, dict]:
    """Collapse long-format rows into { part_code: { key: entry } }."""
    grouped: dict[str, dict] = defaultdict(dict)

    for line_no, rec in rows:
        code = _cell(rec.get("part_code"))
        key = _cell(rec.get(key_column))
        if not code and not key:
            continue
        if not code:
            errors.append(f"{sheet_name} row {line_no}: missing part_code")
            continue
        if not key:
            errors.append(f"{sheet_name} row {line_no}: missing {key_column}")
            continue

        ctx = f"{sheet_name}[{code}/{key}]"
        if key in grouped[code]:
            errors.append(f"{ctx}: duplicate -- the later row wins")

        try:
            grouped[code][key] = build_entry(rec, ctx)
        except ValueError as e:
            errors.append(str(e))

    return grouped


def _assemble(
    part_records: list[tuple[int, dict]],
    dims_by_part: dict[str, dict],
    defects_by_part: dict[str, dict],
    errors: list[str],
) -> list[PartRow]:
    rows: list[PartRow] = []
    seen: set[str] = set()

    for line_no, rec in part_records:
        code = _cell(rec.get("part_code"))
        if not code:
            if any(_cell(v) for v in rec.values()):
                errors.append(f"{PARTS_SHEET} row {line_no}: missing part_code")
            continue
        if code in seen:
            errors.append(f"{code}: appears more than once on the {PARTS_SHEET} sheet")
            continue
        if len(code) > MAX_PART_CODE_LEN:
            errors.append(f"{code}: part_code exceeds {MAX_PART_CODE_LEN} characters")
            continue
        seen.add(code)

        try:
            weight = _to_float(rec.get("part_weight"))
        except ValueError as e:
            errors.append(f"{code}: part_weight {e}")
            weight = None

        category = _cell(rec.get("category_name"))

        rows.append(
            PartRow(
                part_code=code,
                part_name=_cell(rec.get("part_name")) or code,
                category_name=category.upper() if category else None,
                part_weight=weight,
                notes=_cell(rec.get("notes")) or None,
                image=rec.get("image") or None,
                dimensions=dims_by_part.get(code) or None,
                defects=defects_by_part.get(code) or None,
            )
        )

    # Parameter rows pointing at a part that never appears are otherwise
    # invisible -- a typo'd code in a 200-row sheet silently drops its limits.
    orphans = (set(dims_by_part) | set(defects_by_part)) - seen
    errors.extend(
        f"{c}: parameter rows reference a part_code absent from the {PARTS_SHEET} sheet"
        for c in sorted(orphans)
    )

    return rows


# ─────────────────────────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────────────────────────
class PartCsvImporter:
    """Parts sheet only -- a flat CSV cannot express the parameter tables."""

    def __init__(self, file):
        raw = file.read() if hasattr(file, "read") else file
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig", errors="replace")
        self._reader = csv.DictReader(io.StringIO(raw))

    def process(self) -> ParseResult:
        errors: list[str] = []
        header_map = _build_header_map(self._reader.fieldnames or [])

        records: list[tuple[int, dict]] = []
        for line_no, raw in enumerate(self._reader, start=2):
            records.append(
                (line_no, {header_map.get(k, _clean(k)): v for k, v in raw.items()})
            )

        rows = _assemble(records, {}, {}, errors)
        return ParseResult(rows=rows, errors=errors)


# ─────────────────────────────────────────────────────────────────
# Excel
# ─────────────────────────────────────────────────────────────────
class PartExcelImporter:
    def __init__(self, file: io.BytesIO):
        if openpyxl is None:
            raise RuntimeError("openpyxl is required for Excel import")
        # read_only is off: SheetImageLoader needs the full workbook model.
        self.wb = openpyxl.load_workbook(file, data_only=True)

    # -- sheet reading ------------------------------------------------
    def _read_sheet(self, name: str, fallback_to_active: bool = False):
        if name in self.wb.sheetnames:
            return self.wb[name]
        return self.wb.active if fallback_to_active else None

    def _rows(self, sheet) -> tuple[list[tuple[int, dict]], dict[str, int]]:
        if sheet is None:
            return [], {}

        row_iter = sheet.iter_rows(values_only=True)
        try:
            raw_headers = next(row_iter)
        except StopIteration:
            return [], {}

        header_map = _build_header_map(raw_headers)
        col_names = {i: header_map.get(h, _clean(h)) for i, h in enumerate(raw_headers)}
        name_to_idx = {v: k for k, v in col_names.items()}

        records = []
        for line_no, raw in enumerate(row_iter, start=2):
            rec = {col_names[i]: v for i, v in enumerate(raw) if i in col_names}
            if any(_cell(v) for v in rec.values()):
                records.append((line_no, rec))
        return records, name_to_idx

    # -- embedded images ----------------------------------------------
    def _attach_images(self, sheet, records, name_to_idx) -> None:
        """Pull a floating image anchored in the image column into raw bytes.

        Part.image holds the image file's own bytes, so this writes PNG
        bytes directly -- no base64 wrapper.
        """
        if SheetImageLoader is None or "image" not in name_to_idx:
            return
        try:
            loader = SheetImageLoader(sheet)
        except Exception:
            return

        col_letter = openpyxl.utils.get_column_letter(name_to_idx["image"] + 1)
        for line_no, rec in records:
            if rec.get("image"):
                continue
            cell = f"{col_letter}{line_no}"
            try:
                if not loader.image_in(cell):
                    continue
                img = loader.get(cell).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                rec["image"] = buf.getvalue()
            except Exception:
                continue

    # -- entry point ---------------------------------------------------
    def process(self) -> ParseResult:
        errors: list[str] = []

        parts_sheet = self._read_sheet(PARTS_SHEET, fallback_to_active=True)
        part_records, name_to_idx = self._rows(parts_sheet)
        if not part_records:
            errors.append(f"No data rows found on the '{PARTS_SHEET}' sheet")
            return ParseResult(rows=[], errors=errors)

        self._attach_images(parts_sheet, part_records, name_to_idx)

        dim_records, _ = self._rows(self._read_sheet(DIMENSIONS_SHEET))
        def_records, _ = self._rows(self._read_sheet(DEFECTS_SHEET))

        dims_by_part = _group_parameters(
            dim_records, "param_name", _dimension_entry, DIMENSIONS_SHEET, errors
        )
        defects_by_part = _group_parameters(
            def_records, "class_name", _defect_entry, DEFECTS_SHEET, errors
        )

        rows = _assemble(part_records, dims_by_part, defects_by_part, errors)
        return ParseResult(rows=rows, errors=errors)


# ─────────────────────────────────────────────────────────────────
# Template
# ─────────────────────────────────────────────────────────────────
def build_template() -> io.BytesIO:
    if openpyxl is None:
        raise RuntimeError("openpyxl is required to build the template")

    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = PARTS_SHEET
    ws.append(PARTS_COLUMNS)
    ws.append(["BOLT-M8-40", "Hex Bolt M8x40", "FASTENERS", 12.4, "reference part"])
    ws.append(["WASHER-M8", "Flat Washer M8", "FASTENERS", 1.1, ""])

    ws_dim = wb.create_sheet(DIMENSIONS_SHEET)
    ws_dim.append(DIMENSIONS_COLUMNS)
    ws_dim.append(["BOLT-M8-40", "shank_diameter_mm", 8.0, 7.8, 8.2, "mm", ""])
    ws_dim.append(["BOLT-M8-40", "length_mm", 40.0, 39.5, 40.5, "mm", ""])
    ws_dim.append(["WASHER-M8", "outer_diameter_mm", 16.0, 15.7, 16.3, "mm", ""])

    ws_def = wb.create_sheet(DEFECTS_SHEET)
    ws_def.append(DEFECTS_COLUMNS)
    ws_def.append(["BOLT-M8-40", "rust", 0.7, "critical", ""])
    ws_def.append(["BOLT-M8-40", "scratch", 0.9, "minor", "cosmetic only"])

    for sheet in (ws, ws_dim, ws_def):
        sheet.freeze_panes = "A2"
        for col in sheet.columns:
            width = max(len(str(c.value or "")) for c in col) + 3
            sheet.column_dimensions[col[0].column_letter].width = min(width, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf