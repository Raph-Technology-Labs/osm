"""Admin-only part and category management: create, and bulk import.

Separate from routers/parts.py, which is operator-readable lookups for the
part-selection step. Both mount at /parts; this one carries the admin role
dependency at the router level so no write route can be added without it.

Part.image holds the image file's own bytes; GET /parts/{part_id}/image
(in the operator router) serves them back.

has_defect_pipeline / has_measurement_pipeline are NOT writable here. They
belong to whatever saves a PartConfig, so a part created through this
router starts with both False even when it already carries parameters.
"""

from __future__ import annotations

import io
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_role
from app.db.db import get_db
from app.models.models import Category, Part
from app.schemas import CategoryOut
from app.services.spreadsheet_import import (
    PartCsvImporter,
    PartExcelImporter,
    build_template,
)

router = APIRouter(
    prefix="/parts",
    tags=["parts-admin"],
    dependencies=[Depends(require_role("administrator"))],
)

MAX_PART_CODE_LEN = 50
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg"}

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════
def _safe_float(value: Any) -> Optional[float]:
    """Form values arrive as strings; blank means 'not provided'."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"'{value}' is not a number")


def _parse_json_form(raw: Optional[str], field: str) -> Optional[dict]:
    if raw is None or raw.strip() == "":
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"{field}: invalid JSON ({e.msg})")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=f"{field}: expected a JSON object")
    return parsed


def _opt_number(entry: dict, key: str, ctx: str) -> Optional[float]:
    value = entry.get(key)
    if value is None or value == "":
        return None
    # bool is an int subclass -- exclude it explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=400, detail=f"{ctx}: {key} must be a number")
    return float(value)


def _validate_defects(raw: Optional[dict]) -> Optional[dict[str, Any]]:
    """Normalize to the Part.defects contract:

        { class_name: { conf_thresh, notes } }

    Keys must match the detection model's class names -- nothing here can
    verify that, so only the shape is enforced.
    """
    if not raw:
        return None

    out: dict[str, Any] = {}
    for class_name, entry in raw.items():
        key = str(class_name).strip()
        if not key:
            raise HTTPException(status_code=400, detail="defects: empty class name")
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail=f"defects[{key}]: expected an object")

        ctx = f"defects[{key}]"
        conf = _opt_number(entry, "conf_thresh", ctx)
        if conf is not None and not (0.0 <= conf <= 1.0):
            raise HTTPException(
                status_code=400, detail=f"{ctx}: conf_thresh must be between 0 and 1"
            )

        out[key] = {
            "conf_thresh": conf,
            "notes": str(entry.get("notes") or "").strip(),
        }

    return out or None


def _validate_dimensions(raw: Optional[dict]) -> Optional[dict[str, Any]]:
    """Normalize to the Part.dimensions contract:

        { param_name: { nominal, upper_limit, lower_limit, unit,
                        calibration_factor, notes } }

    calibration_factor scales the raw measurement before it is compared
    against the limits (see CameraResult.measurement_data). Defaults to
    None, which the pipeline treats as 1.0.
    """
    if not raw:
        return None

    out: dict[str, Any] = {}
    for param_name, entry in raw.items():
        key = str(param_name).strip()
        if not key:
            raise HTTPException(status_code=400, detail="dimensions: empty parameter name")
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail=f"dimensions[{key}]: expected an object")

        ctx = f"dimensions[{key}]"
        nominal = _opt_number(entry, "nominal", ctx)
        upper = _opt_number(entry, "upper_limit", ctx)
        lower = _opt_number(entry, "lower_limit", ctx)
        cal = _opt_number(entry, "calibration_factor", ctx)

        # A zero or negative factor would silently zero out or invert every
        # measurement for this parameter, so it is rejected outright.
        if cal is not None and cal <= 0:
            raise HTTPException(
                status_code=400, detail=f"{ctx}: calibration_factor must be greater than 0"
            )

        if lower is not None and upper is not None and lower > upper:
            raise HTTPException(status_code=400, detail=f"{ctx}: lower_limit is above upper_limit")
        if nominal is not None and lower is not None and nominal < lower:
            raise HTTPException(status_code=400, detail=f"{ctx}: nominal is below lower_limit")
        if nominal is not None and upper is not None and nominal > upper:
            raise HTTPException(status_code=400, detail=f"{ctx}: nominal is above upper_limit")

        out[key] = {
            "nominal": nominal,
            "upper_limit": upper,
            "lower_limit": lower,
            "unit": str(entry.get("unit") or "").strip(),
            "calibration_factor": cal,
            "notes": str(entry.get("notes") or "").strip(),
        }

    return out or None


def _resolve_category(
    db: Session, category_id: Optional[int], category_name: Optional[str]
) -> Category:
    """Look up by id, else find-or-create by name (case-insensitive).

    Names are stored uppercase so 'bolts' from a spreadsheet and 'BOLTS'
    from the form never become two rows. Flushes but does not commit --
    the caller owns the transaction.
    """
    if category_id is not None:
        category = db.get(Category, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="category_id not found")
        return category

    if category_name and category_name.strip():
        name = category_name.strip()
        existing = db.query(Category).filter(Category.category_name.ilike(name)).first()
        if existing:
            return existing
        category = Category(category_name=name.upper())
        db.add(category)
        db.flush()
        return category

    raise HTTPException(status_code=400, detail="Provide either category_id or category_name")


async def _read_image(image: Optional[UploadFile]) -> Optional[bytes]:
    """Store the image file's own bytes. No base64 wrapper: it costs ~33%
    extra storage and forces the bytes through a text encode/decode on
    every read. GET /parts/{id}/image serves them back directly."""
    if image is None or not image.filename:
        return None
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Image must be PNG or JPEG")

    data = await image.read()
    if not data:
        return None
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 5 MB")
    return data


# ═════════════════════════════════════════════════════════════════
# Categories
# ═════════════════════════════════════════════════════════════════
@router.post("/categories", response_model=CategoryOut, status_code=201)
def add_category(payload: dict, db: Session = Depends(get_db)):
    name = str(payload.get("category_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="category_name is required")

    if db.query(Category).filter(Category.category_name.ilike(name)).first():
        raise HTTPException(status_code=409, detail="Category already exists")

    category = Category(category_name=name.upper())
    db.add(category)
    db.commit()
    db.refresh(category)
    return CategoryOut(
        category_id=category.category_id, category_name=category.category_name
    )


# ═════════════════════════════════════════════════════════════════
# Single part
# ═════════════════════════════════════════════════════════════════
@router.post("", status_code=201)
async def add_part(
    part_name: str = Form(...),
    part_code: str = Form(...),
    category_id: Optional[int] = Form(None),
    category_name: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    part_weight: Optional[str] = Form(None),
    defects: Optional[str] = Form(None),      # JSON string
    dimensions: Optional[str] = Form(None),   # JSON string
    image: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    code = part_code.strip()
    name = part_name.strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="part_code and part_name are required")
    if len(code) > MAX_PART_CODE_LEN:
        raise HTTPException(
            status_code=400, detail=f"part_code exceeds {MAX_PART_CODE_LEN} characters"
        )
    if db.query(Part).filter(Part.part_code == code).first():
        raise HTTPException(status_code=409, detail="part_code already exists")

    # Validate everything before touching the session, so a bad payload
    # cannot leave a half-created category behind.
    weight = _safe_float(part_weight)
    parsed_defects = _validate_defects(_parse_json_form(defects, "defects"))
    parsed_dimensions = _validate_dimensions(_parse_json_form(dimensions, "dimensions"))
    image_bytes = await _read_image(image)

    category = _resolve_category(db, category_id, category_name)

    part = Part(
        part_code=code,
        part_name=name,
        category_id=category.category_id,
        notes=(notes or "").strip() or None,
        part_weight=weight,
        image=image_bytes,
        defects=parsed_defects,
        dimensions=parsed_dimensions,
    )

    db.add(part)
    db.commit()
    db.refresh(part)

    return {
        "message": "Part added successfully",
        "part_id": part.part_id,
        "part_code": part.part_code,
        "category_id": category.category_id,
    }


# ═════════════════════════════════════════════════════════════════
# Bulk import
# ═════════════════════════════════════════════════════════════════
@router.get("/bulk-upload-template")
def bulk_upload_template():
    return StreamingResponse(
        build_template(),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="OSM_BulkUpload_Template.xlsx"'
        },
    )


@router.post("/bulk-upload")
async def bulk_upload_parts(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    filename = (file.filename or "").lower()
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    if filename.endswith(".csv"):
        result = PartCsvImporter(contents).process()
    elif filename.endswith((".xlsx", ".xlsm")):
        result = PartExcelImporter(io.BytesIO(contents)).process()
    else:
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx are supported")

    # Nothing usable in the file at all -- a 400 is more honest than a
    # success response reporting zero created.
    if not result.rows:
        raise HTTPException(
            status_code=400,
            detail=result.errors[0] if result.errors else "No parts found in the file",
        )

    created = with_dims = with_defects = 0
    errors = list(result.errors)

    for row in result.rows:
        try:
            if db.query(Part).filter(Part.part_code == row.part_code).first():
                errors.append(f"{row.part_code}: already exists")
                continue

            category = (
                _resolve_category(db, None, row.category_name)
                if row.category_name
                else None
            )

            part = Part(
                part_code=row.part_code,
                part_name=row.part_name,
                category_id=category.category_id if category else None,
                notes=row.notes,
                part_weight=row.part_weight,
                image=row.image,
                dimensions=row.dimensions,
                defects=row.defects,
            )
            db.add(part)
            # Flush per row so a failure rolls back only this row -- without
            # it, one bad row discards every part flushed earlier in the
            # batch while the counters still report them as created.
            db.flush()

            created += 1
            with_dims += bool(part.dimensions)
            with_defects += bool(part.defects)
        except HTTPException as e:
            db.rollback()
            errors.append(f"{row.part_code}: {e.detail}")
        except Exception as e:  # noqa: BLE001 -- one bad row must not sink the batch
            db.rollback()
            errors.append(f"{row.part_code}: {e}")

    db.commit()

    return {
        "created_parts": created,
        "with_dimensions": with_dims,
        "with_defects": with_defects,
        "errors": errors,
    }