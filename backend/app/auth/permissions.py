# backend/app/auth/permissions.py
"""
Role gate for admin-only routes.

You already have an app/auth/ package and routers/auth.py, so if there is
a current-user dependency in there, DELETE get_current_user below and
import yours instead -- require_admin is the only part that matters.

As written, identity comes from an `X-User-Id` header and is re-checked
against the DB on every call. That is not authentication; it is the
authorisation hook placed where it belongs, so swapping in JWT later
touches only get_current_user and no route signature.
"""
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.db import SessionLocal
from app.models.models import User

ADMIN_ROLES = ("administrator", "superadministrator")


def get_db():
    """Drop this if app/db/ already exports a session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> User:
    # ── replace this block with token decoding when auth lands ──────
    if x_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user = db.query(User).filter(User.id == x_user_id).first()
    # ────────────────────────────────────────────────────────────────
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user",
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """administrator | superadministrator"""
    if user.role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Editing part details requires administrator access",
        )
    return user


def require_superadmin(user: User = Depends(get_current_user)) -> User:
    if user.role != "superadministrator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires superadministrator access",
        )
    return user