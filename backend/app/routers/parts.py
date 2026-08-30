"""Category/part lookups for the Create Session part-selection step.

Read-only lookups against Part/Category -- no session or pipeline logic here
(CLAUDE.md Section 12: routes stay thin). Image is stored as a UTF-8-encoded
data-URI string in Part.image (LargeBinary), matching the raph-vision/GCM
convention -- decode and return inline, no separate image endpoint.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.db import get_db
from app.models.models import Category, Part
from app.schemas import CategoryOut, PartOut

router = APIRouter(prefix="/parts", tags=["parts"])


@router.get("/categories", response_model=list[CategoryOut])
def get_categories(db: Session = Depends(get_db)):
    categories = db.query(Category).order_by(Category.category_name).all()
    return [
        CategoryOut(category_id=c.category_id, category_name=c.category_name)
        for c in categories
    ]


@router.get("", response_model=list[PartOut])
def get_parts_by_category(category_id: int = Query(...), db: Session = Depends(get_db)):
    parts = (
        db.query(Part)
        .filter(Part.category_id == category_id)
        .order_by(Part.part_name)
        .all()
    )
    return [
        PartOut(
            part_id=p.part_id,
            part_code=p.part_code,
            part_name=p.part_name,
            part_weight=p.part_weight,
            dimensions=p.dimensions,
            image=p.image.decode("utf-8") if p.image else None,
        )
        for p in parts
    ]
