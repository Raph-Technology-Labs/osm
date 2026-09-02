# Task: Auth Slice — Login (backend + frontend)

## Context

raph-vision is a FastAPI + React (MUI) app for industrial part inspection. This is the first vertical slice: real login, replacing the current placeholder auth (empty `LoginPage.jsx`, `localStorage`-only `loginData` read in `MainLayout.jsx` with no actual verification).

Read `CLAUDE.md` for full project context before starting. Do not touch any files outside what's listed below — this is a narrowly scoped slice.

**Process: present a plan first (files to add/change, function signatures, no full implementations) and wait for confirmation before writing code.**

## Existing files relevant to this task (read, don't assume)

- `backend/app/models/models.py` — `User` model already exists: `id`, `name`, `username`, `password_hash`, `role`
- `backend/app/db/db.py` — existing `get_db()` dependency, keep using this pattern
- `backend/app/main.py` — existing FastAPI app, CORS already configured
- `backend/app/routers/routers.py` — existing router pattern to follow
- `frontend/src/pages/LoginPage.jsx` — currently empty, build this
- `frontend/src/layouts/MainLayout.jsx` — currently reads `loginData` from `localStorage` directly; update to use a proper auth context instead
- `frontend/src/api/axios.js` — currently empty, set up the base axios instance + auth here
- `frontend/src/routes/AppRoutes.jsx` — existing routes, add a protected-route wrapper
- `frontend/src/theme/theme.js` — use existing theme tokens for styling, don't hardcode colors

## Backend — what to build

**New files:**
- `backend/app/core/config.py` — `pydantic-settings` based `Settings` class: `DATABASE_URL`, `JWT_SECRET`, `JWT_ALGORITHM` (default `HS256`), `JWT_EXPIRE_MINUTES` (default `60`). Replace the raw `os.getenv("DATABASE_URL")` in `db.py` with this.
- `backend/app/core/security.py` — password hashing (`bcrypt` via `passlib`) and JWT create/decode functions.
- `backend/app/schemas/auth.py` — Pydantic models: `UserLogin` (username, password), `Token` (access_token, token_type).
- `backend/app/schemas/user.py` — `UserOut` (id, name, username, role — never password_hash).
- `backend/app/routers/auth.py` — `POST /auth/login`, `GET /auth/me`, plus a `get_current_user` dependency and a `require_role(role: str)` dependency factory for later use by other slices.

**Behavior:**
- `POST /auth/login` — body: `UserLogin`. Look up user by username, verify password with bcrypt. On success, return `Token` (JWT with `sub` = username, expires per config). On failure, `401` with a generic message ("Incorrect username or password") — don't reveal whether it was the username or password that was wrong.
- `GET /auth/me` — protected by `get_current_user`, returns `UserOut` for the current token's user. Use this to smoke-test the whole flow via `/docs`.
- `get_current_user` — `OAuth2PasswordBearer(tokenUrl="auth/login")`, decodes JWT, loads `User` from DB, raises `401` if token invalid/expired/user not found.
- Register the new router in `main.py`.

**New dependencies** (add to `backend/requirements.txt`, install with `pip install "passlib[bcrypt]" python-jose[cryptography] pydantic-settings --break-system-packages` in the dev container):
- `passlib[bcrypt]`
- `python-jose[cryptography]`
- `pydantic-settings`

**Tests** (`backend/tests/`, new test DB or schema, don't run against dev data):
- `test_login_success` — valid credentials → 200, returns a token
- `test_login_wrong_password` — invalid password → 401
- `test_login_unknown_user` → 401
- `test_me_requires_token` — no `Authorization` header → 401
- `test_me_with_valid_token` — returns correct `UserOut`

## Frontend — what to build

**New/changed files:**
- `frontend/src/api/axios.js` — axios instance with base URL from an env var (`REACT_APP_API_URL`), request interceptor attaching `Authorization: Bearer <token>` from stored token, response interceptor redirecting to `/login` on 401.
- `frontend/src/context/AuthContext.jsx` (new) — React context holding `user`, `token`, `login(username, password)`, `logout()`. Persists token to `localStorage`, hydrates on app load. Replace `MainLayout.jsx`'s direct `localStorage.getItem("loginData")` read with this context.
- `frontend/src/pages/LoginPage.jsx` — MUI form (username, password fields, submit button), calls `AuthContext.login`, shows an error `Alert` on failure (map the backend's 401 message), redirects to `/` on success. Follow the existing visual style from `ModeSelectionPage.jsx` (theme gradients, card styling) — keep it consistent, don't introduce a new visual language.
- `frontend/src/routes/ProtectedRoute.jsx` (new) — wraps children, redirects to `/login` if no valid auth context user, used to wrap the existing `<Routes>` in `AppRoutes.jsx`.
- `frontend/src/routes/AppRoutes.jsx` — add `/login` route (unprotected), wrap all existing routes in `ProtectedRoute`.
- `frontend/src/App.js` / `frontend/src/index.js` — wrap the app in `AuthContext`'s provider.

**Behavior:**
- Visiting any route while logged out → redirected to `/login`.
- Successful login → token stored, redirected to `/` (Dashboard).
- `Sidebar.jsx`'s existing `loginData`/`isAdmin`/`isSuperAdmin` checks and the "User" display block should read from the new `AuthContext` instead of the raw `localStorage` parsing — update minimally, don't restructure `Sidebar.jsx` beyond this.
- Logout (`Sidebar.jsx`'s existing `/signout` button target) should call `AuthContext.logout()` and redirect to `/login`.

## Explicitly out of scope for this slice

- User registration/creation UI (users are assumed to already exist in the DB for now)
- Refresh tokens (access-token-only, per architecture decision)
- Password reset flow
- Any change to `part_operation_modes`, sessions, or any other table/route
- **Finalizing the role list/hierarchy** — `role` is a free-text column (`Text`, no `CheckConstraint`), roles seen so far are `administrator`/`superadministrator` (used in `Sidebar.jsx`). Don't hardcode a fixed role enum or add a DB constraint in this slice — `require_role(role: str)` takes any string, keep it generic. The actual role list/permissions model will be decided incrementally as more slices need role checks.

## Definition of done

- `POST /auth/login` works via `/docs` with a real user from the DB
- `GET /auth/me` works with a valid token, 401s without one
- Frontend: can log in through the UI, land on Dashboard, refresh the page and stay logged in (token persisted), log out and get redirected to `/login`, and hitting a protected route while logged out redirects to `/login`
- All 5 backend tests pass
- No changes to files outside what's listed above
