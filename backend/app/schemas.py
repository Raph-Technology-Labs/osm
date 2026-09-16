"""Pydantic request/response models -- shared across routers (CLAUDE.md Section 12)."""

from typing import Optional

from pydantic import BaseModel

import base64
import binascii
import re
from datetime import datetime
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class CategoryOut(BaseModel):
    category_id: int
    category_name: str


class PartOut(BaseModel):
    part_id: int
    part_code: str
    part_name: str
    part_weight: Optional[float] = None
    dimensions: Optional[dict] = None
    # image: Optional[str] = None
    # Served by GET /parts/{part_id}/image rather than inlined -- a category
    # listing would otherwise carry every part's photo.
    has_image: bool = False

# ─────────────────────────────────────────────────────────────────
# PART DETAILS
#
# Two models per JSON column: a permissive OUTPUT shape that accepts
# whatever is already stored, and a strict INPUT shape carrying the same
# rules parts_admin applies on create. parts_admin writes explicit nulls
# and allows a parameter with no limits, so validating on the way out
# would 500 the listing on parts added through the Add Part form.
# ─────────────────────────────────────────────────────────────────

MAX_IMAGE_BYTES = 5 * 1024 * 1024          # matches parts_admin

Severity = Literal["critical", "major", "minor"]


def _clean_keys(d: dict, what: str) -> dict:
    """
    Keys are free-hand (they must match the model's class name or the
    measurement step's output name), so they are trimmed and checked for
    emptiness and duplicates -- not forced into a slug.
    """
    out, seen = {}, set()
    for key, value in d.items():
        k = key.strip()
        if not k:
            raise ValueError(f"{what} name cannot be blank")
        if k.lower() in seen:
            raise ValueError(f"Duplicate {what} name '{k}'")
        seen.add(k.lower())
        out[k] = value
    return out


class DimensionSpec(BaseModel):
    """OUTPUT shape -- deliberately permissive, see the note above."""
    nominal: Optional[float] = None
    upper_limit: Optional[float] = None
    lower_limit: Optional[float] = None
    unit: Optional[str] = None
    calibration_factor: Optional[float] = None
    notes: Optional[str] = None


class DimensionIn(DimensionSpec):
    """INPUT shape -- the rules parts_admin._validate_dimensions applies."""

    @model_validator(mode="after")
    def _check_band(self) -> "DimensionIn":
        lo, hi, nom, cal = (
            self.lower_limit, self.upper_limit, self.nominal, self.calibration_factor,
        )
        # zero or negative would silently zero out or invert every
        # measurement for this parameter
        if cal is not None and cal <= 0:
            raise ValueError("calibration_factor must be greater than 0")
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("lower_limit is above upper_limit")
        if nom is not None and lo is not None and nom < lo:
            raise ValueError("nominal is below lower_limit")
        if nom is not None and hi is not None and nom > hi:
            raise ValueError("nominal is above upper_limit")
        return self


class DefectSpec(BaseModel):
    """OUTPUT shape. severity is not written by parts_admin, so it is
    absent on every part created through the Add Part form."""
    conf_thresh: Optional[float] = None
    severity: Optional[Severity] = None
    notes: Optional[str] = None


class DefectIn(DefectSpec):
    conf_thresh: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class PartDetailOut(PartOut):
    """
    PartOut plus everything the Part Details table and edit dialog need.
    Image still follows the PartOut rule -- has_image only, bytes come
    from the image endpoint.
    """
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    notes: Optional[str] = None

    # narrows PartOut.dimensions (Optional[dict]) to the typed shape
    dimensions: Dict[str, DimensionSpec] = Field(default_factory=dict)
    defects: Dict[str, DefectSpec] = Field(default_factory=dict)

    has_defect_pipeline: bool = False
    has_measurement_pipeline: bool = False
    active_config_version: Optional[int] = None

    created_at: Optional[datetime] = None
    created_by_name: Optional[str] = None


class PartUpdate(BaseModel):
    """
    Full replacement of the editable fields.

    part_code is absent on purpose -- it is the barcode identity and is
    denormalized onto PartSession, so it is immutable once created.
    """
    part_name: str = Field(min_length=1, max_length=200)
    category_id: Optional[int] = None
    part_weight: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=2000)

    dimensions: Dict[str, DimensionIn] = Field(default_factory=dict)
    defects: Dict[str, DefectIn] = Field(default_factory=dict)

    # data URI ("data:image/png;base64,...") or bare base64; None = leave as-is.
    # JSON endpoint, so no multipart like parts_admin's create.
    image: Optional[str] = None
    clear_image: bool = False

    @field_validator("dimensions")
    @classmethod
    def _dim_keys(cls, v):
        return _clean_keys(v, "parameter")

    @field_validator("defects")
    @classmethod
    def _defect_keys(cls, v):
        return _clean_keys(v, "defect")

    def decoded_image(self) -> Optional[bytes]:
        """Data URI -> bytes for the LargeBinary column. None if nothing sent."""
        if not self.image:
            return None
        raw = self.image
        if raw.startswith("data:"):
            _, _, raw = raw.partition(",")
        try:
            blob = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("image is not valid base64")
        if len(blob) > MAX_IMAGE_BYTES:
            raise ValueError(
                f"image is {len(blob) // 1024} KB, limit is {MAX_IMAGE_BYTES // 1024} KB"
            )
        if not (blob.startswith(b"\x89PNG") or blob.startswith(b"\xff\xd8\xff")):
            raise ValueError("image must be PNG or JPEG")
        return blob