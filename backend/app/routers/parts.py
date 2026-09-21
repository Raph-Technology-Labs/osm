"""Category/part lookups for the Create Session part-selection step.

Read-only lookups against Part/Category -- no session or pipeline logic here
(CLAUDE.md Section 12: routes stay thin). Image is stored as a UTF-8-encoded
data-URI string in Part.image (LargeBinary), matching the raph-vision/GCM
convention -- decode and return inline, no separate image endpoint.
"""

from fastapi import APIRouter, Depends, Query, Response 
from sqlalchemy.orm import Session

from app.auth.dependencies import require_role
from app.db.db import get_db
from app.models.models import Category, Part
from app.schemas import CategoryOut, PartOut

router = APIRouter(prefix="/parts", tags=["parts"], dependencies=[Depends(require_role("operator"))])

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

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
            has_image=p.image is not None,
        )
        for p in parts
    ]

@router.get("/{part_id}/image")
def get_part_image(part_id: int, db: Session = Depends(get_db)):
    """Serve the stored bytes. Content type comes from the magic bytes, so
    the model needs no mime column."""
    part = db.get(Part, part_id)
    if not part or not part.image:
        raise HTTPException(status_code=404, detail="No image for this part")

    media_type = "image/png" if part.image[:8] == PNG_SIGNATURE else "image/jpeg"
    return Response(
        content=part.image,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )