"""Pydantic request/response models -- shared across routers (CLAUDE.md Section 12)."""

from typing import Optional

from pydantic import BaseModel


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
