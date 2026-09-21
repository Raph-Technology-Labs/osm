# backend/app/api/deps.py
"""
Shared FastAPI dependencies.

AUTH NOTE
─────────
Right now the frontend has no token — login returns a plain dict from
User.can_login() and the UI holds it in `loginData`. So the identity here is
read from an `X-User-Id` header and re-checked against the DB on every write.

That is NOT authentication — it is authorisation plumbing, put in the right
place so it can be swapped without touching any route. When you add JWT (or
sessions), the only thing that changes is the body of `get_current_user`;
`require_admin` and every route using it stay exactly as they are.
"""
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.db import SessionLocal
from app.models.models import User

ADMIN_ROLES = ("administrator", "superadministrator")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> User:
    # ── swap this block for token decoding when auth lands ──────────
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
    """Administrator or superadministrator only."""
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