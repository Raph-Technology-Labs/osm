# Spec 8 — Sidebar Role-Based Access

## Context

Show/hide sidebar items and gate certain actions based on the logged-in user's role, following GCM's existing role-based access pattern (not inventing a new one — raph-vision's `User.role` and `Sidebar.jsx`'s `isAdmin`/`isSuperAdmin` checks are meant to match GCM's model).

**Before planning: read GCM's existing role-based access implementation directly** (frontend role checks, and how it enforces role-gating on both UI and backend) — same as the instruction given for the auth slice (`specs/07_claude_code_auth_slice_prompt.md`). Read `CLAUDE.md` for project context.

**Process: present a plan first (files to add/change, function signatures, no full implementations) and wait for confirmation before writing code.**

## Existing files relevant to this task

- `frontend/src/components/Sidebar.jsx` — already has `isAdmin`/`isSuperAdmin` checks reading raw `loginData` — this spec should update these to read from `AuthContext` (built in the auth slice) instead, and extend gating to any new sidebar items added by other specs (Device Settings, Health Check) if not already covered.
- `frontend/src/context/AuthContext.jsx` (from the auth slice) — `user.role` is the source of truth.
- `backend/app/routers/auth.py` (from the auth slice) — `require_role(role: str)` dependency already exists; this spec is primarily frontend, but confirm any backend routes touched by gated sidebar actions (e.g. Add Item / Add Part) actually enforce `require_role` server-side too — UI hiding alone is not real access control.

## What to build

**Changed files:**
- `frontend/src/components/Sidebar.jsx` — replace raw `localStorage`/`loginData` role checks with `AuthContext`-sourced role, matching GCM's pattern for which roles see which items. Confirm the exact role list and per-item visibility rules against GCM's implementation during planning, don't assume the current `administrator`/`superadministrator` split is complete or correct without checking.
- Any other pages/components with inline role checks (audit for these during planning — grep for `role ===` or similar patterns across the frontend) should be updated consistently, not left mismatched with the Sidebar's logic.

**Behavior:**
- A user without permission for a given action should not see the option to take it (UI-level hiding), AND the corresponding backend route must independently reject the action via `require_role` if attempted directly (e.g. via API) — confirm this is true for every gated action touched by this spec, don't assume it's already covered.
- Role list should remain whatever GCM's actual roles are — don't hardcode assumptions beyond what GCM defines.

**Tests (frontend, if a testing pattern exists in the repo — otherwise document manual test steps):**
- Logged in as each role GCM defines, confirm the sidebar shows the correct set of items
- Confirm a non-admin cannot access an admin-only route by direct URL navigation (not just hidden from the sidebar)

## Explicitly out of scope for this spec

- Adding new roles beyond what GCM already defines
- Backend `require_role` implementation itself — that already exists from the auth slice; this spec confirms it's applied correctly to any new routes introduced by other specs, not built from scratch

## Definition of done

- Sidebar visibility matches GCM's role-based pattern, sourced from `AuthContext` rather than raw `localStorage`
- Every gated frontend action has a matching server-side `require_role` check — verified, not assumed
- Direct URL navigation to a restricted page by an unauthorized role is blocked or redirected, not just hidden from navigation
- No changes to files outside what's listed above (plus whatever audit-identified inline role checks are found during planning — list these explicitly in the plan before touching them)
