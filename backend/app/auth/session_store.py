"""In-memory session-token store (CLAUDE.md Security section: "server-side
session (in-memory dict or Redis, already in the stack), opaque session
token issued at login -- no JWT/refresh flow, this runs locally in
Electron, not across services or browsers"). Redis isn't running natively
on this dev machine tonight, and a single-process FastAPI server doesn't
need it for correctness -- swap this module for a Redis-backed one later
without changing dependencies.py's interface if multi-process ever becomes
real.

No expiry logic: "long-lived is fine (operator shouldn't get logged out
mid-shift); tie invalidation to explicit logout or app close" (CLAUDE.md).
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class SessionInfo:
    user_id: int
    username: str
    name: str
    role: str


_sessions: Dict[str, SessionInfo] = {}
_lock = threading.Lock()


def create_session(user_id: int, username: str, name: str, role: str) -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions[token] = SessionInfo(user_id=user_id, username=username, name=name, role=role)
    return token


def get_session(token: str) -> Optional[SessionInfo]:
    with _lock:
        return _sessions.get(token)


def destroy_session(token: str) -> None:
    with _lock:
        _sessions.pop(token, None)
