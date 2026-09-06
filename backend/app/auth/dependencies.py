"""FastAPI dependency enforcing role checks at the route level -- backend
side, per CLAUDE.md Critical Rule 6 ("Role checks are backend-enforced, not
frontend-only. A hidden button is not access control."). Every route that
needs auth takes `Depends(require_role("operator"))` (or "administrator" /
"superadministrator") as a parameter; FastAPI runs it before the handler.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from app.auth.session_store import SessionInfo, get_session

# Operator ⊂ Admin ⊂ Super Admin (CLAUDE.md Section 2) -- each role can do
# everything the roles below it can.
_ROLE_RANK = {"operator": 0, "administrator": 1, "superadministrator": 2}


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    return authorization.removeprefix("Bearer ").strip()


def get_current_user(authorization: str | None = Header(default=None)) -> SessionInfo:
    token = _extract_token(authorization)
    session = get_session(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    return session


def require_role(min_role: str):
    """Returns a FastAPI dependency requiring at least `min_role`
    (operator/administrator/superadministrator, per the Operator ⊂ Admin ⊂
    Super Admin hierarchy)."""
    if min_role not in _ROLE_RANK:
        raise ValueError(f"Unknown role {min_role!r} -- must be one of {sorted(_ROLE_RANK)}")

    def dependency(authorization: str | None = Header(default=None)) -> SessionInfo:
        user = get_current_user(authorization)
        if _ROLE_RANK[user.role] < _ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=403,
                detail=f"Requires role {min_role!r} or higher, have {user.role!r}",
            )
        return user

    return dependency
