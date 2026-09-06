"""Login/logout -- issues the opaque session token every other route's
require_role() dependency checks. Reuses User.can_login() (already existed
in models.py, password hashing + role lookup, just had no route in front
of it)."""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.auth.session_store import create_session, destroy_session
from app.models.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: int
    name: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    result = User.can_login(body.username, body.password)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_session(
        user_id=result["user_id"], username=body.username, name=result["user_name"], role=result["role"]
    )
    return LoginResponse(token=token, user_id=result["user_id"], name=result["user_name"], role=result["role"])


@router.post("/logout")
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        destroy_session(authorization.removeprefix("Bearer ").strip())
    return {"status": "logged_out"}


@router.get("/me", response_model=LoginResponse)
def me(authorization: str | None = Header(default=None)):
    session = get_current_user(authorization)
    return LoginResponse(token="", user_id=session.user_id, name=session.name, role=session.role)
