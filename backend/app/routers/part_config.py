"""Per-part machine config: read, create (superadmin), edit (admin+).

Every save inserts a NEW PartConfig row and deactivates the previous one,
so the immediate previous version is always recoverable after a bad edit.
Old rows are never deleted -- PartSession.part_config_id points at them, and
that is what makes a past run's settings reproducible.

The active row is the source of truth; app/config/machine_config_<part_code>
.yaml is rewritten from it on every save, so a hand-edited or stale file
cannot silently change machine behaviour.

An unconfigured part returns a BLANK form, not another part's values --
these numbers decide what the machine physically does, and a prefilled
form invites saving someone else's station offsets unread.

Routes stay thin (CLAUDE.md Section 12) -- all YAML work lives in
app/config/config_builder.py.
"""

from __future__ import annotations

from typing import Any, Optional
from fastapi.responses import Response
from app.config.config_builder import config_filename
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_role
from app.config.config_builder import (
    build_config,
    empty_form,
    form_from_config,
    parse_yaml,
    render_yaml,
    validate_config,
    validate_form,
    write_config_file,
)
from app.db.db import get_db
from app.models.models import Part, PartConfig, PartSession

router = APIRouter(prefix="/parts", tags=["part-config"])


class ConfigPayload(BaseModel):
    form: dict[str, Any]
    notes: Optional[str] = None


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════
def _get_part(db: Session, part_id: int) -> Part:
    part = db.get(Part, part_id)
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    return part


def _active(db: Session, part_id: int) -> Optional[PartConfig]:
    return (
        db.query(PartConfig)
        .filter(PartConfig.part_id == part_id, PartConfig.is_active.is_(True))
        .first()
    )


def _previous(db: Session, part_id: int) -> Optional[PartConfig]:
    """The most recent superseded version -- what a restore rolls back to."""
    return (
        db.query(PartConfig)
        .filter(PartConfig.part_id == part_id, PartConfig.is_active.is_(False))
        .order_by(PartConfig.version.desc())
        .first()
    )


def _next_version(db: Session, part_id: int) -> int:
    highest = (
        db.query(PartConfig.version)
        .filter(PartConfig.part_id == part_id)
        .order_by(PartConfig.version.desc())
        .first()
    )
    return (highest[0] + 1) if highest else 1


def _block_if_running(db: Session, part: Part) -> None:
    """Refuse edits while a session is using this config.

    Otherwise a tolerance changes mid-run and that session's pass/fail
    results can no longer be reproduced.
    """
    running = (
        db.query(PartSession)
        .filter(
            PartSession.part_id == part.part_id,
            PartSession.session_end.is_(None),
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Session {running.id} is still running for this part. "
                "Stop it before editing the config."
            ),
        )


def _commit_version(
    db: Session,
    part: Part,
    yaml_text: str,
    cfg: dict,
    user_id: Optional[int],
    notes: Optional[str],
) -> PartConfig:
    """Insert a new active version, standing the current one down.

    Both the is_active flag and Part.active_config_id are updated in one
    transaction -- leaving two rows active would make "which config runs?"
    depend on row order.
    """
    db.query(PartConfig).filter(
        PartConfig.part_id == part.part_id, PartConfig.is_active.is_(True)
    ).update({"is_active": False}, synchronize_session=False)

    config = PartConfig(
        part_id=part.part_id,
        version=_next_version(db, part.part_id),
        config_yaml=yaml_text,
        config_path=write_config_file(part.part_code, yaml_text),
        is_active=True,
        created_by=user_id,
        notes=notes,
    )
    db.add(config)
    db.flush()

    part.active_config_id = config.id

    # These flags are owned by the config, not the part form -- this is the
    # only place that knows whether a pipeline was actually configured.
    stations = cfg.get("stations", [])
    part.has_defect_pipeline = any(
        "defect" in (s.get("pipeline") or {}) for s in stations
    )
    part.has_measurement_pipeline = any(
        "measurement" in (s.get("pipeline") or {}) for s in stations
    )

    db.commit()
    db.refresh(config)
    return config


def _save(
    db: Session, part: Part, payload: ConfigPayload, user_id: Optional[int]
) -> PartConfig:
    try:
        # Blanks first, so the person is told which field is empty rather
        # than which derived structure failed downstream.
        validate_form(payload.form)
        cfg = build_config(part, payload.form)
        validate_config(cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _commit_version(db, part, render_yaml(cfg), cfg, user_id, payload.notes)


def _version_summary(config: Optional[PartConfig]) -> Optional[dict]:
    if not config:
        return None
    return {
        "config_id": config.id,
        "version": config.version,
        "created_at": config.created_at,
        "created_by": config.created_by,
        "notes": config.notes,
    }


# ═════════════════════════════════════════════════════════════════
# Routes
# ═════════════════════════════════════════════════════════════════
@router.get("/{part_id}/config", dependencies=[Depends(require_role("operator"))])
def get_part_config(part_id: int, db: Session = Depends(get_db)):
    """Form values for this part's active config.

    `exists: false` means nothing is saved yet and the form comes back
    blank -- this part is not configured and cannot run a session.

    `previous` describes the version one save back, for the restore button.
    """
    part = _get_part(db, part_id)
    config = _active(db, part_id)

    base = {
        "part_id": part.part_id,
        "part_code": part.part_code,
        "part_name": part.part_name,
        "dimensions": part.dimensions or {},
        "defects": part.defects or {},
    }

    if not config:
        return {
            **base,
            "exists": False,
            "form": empty_form(),
            "config_yaml": None,
            "config_path": None,
            "version": None,
            "updated_at": None,
            "previous": None,
        }

    return {
        **base,
        "exists": True,
        "form": form_from_config(parse_yaml(config.config_yaml)),
        "config_yaml": config.config_yaml,
        "config_path": config.config_path,
        "version": config.version,
        "updated_at": config.created_at,
        "previous": _version_summary(_previous(db, part_id)),
    }


@router.get(
    "/{part_id}/config/versions",
    dependencies=[Depends(require_role("administrator"))],
)
def list_config_versions(part_id: int, db: Session = Depends(get_db)):
    """Full history, newest first. Sessions reference these rows by id."""
    _get_part(db, part_id)
    rows = (
        db.query(PartConfig)
        .filter(PartConfig.part_id == part_id)
        .order_by(PartConfig.version.desc())
        .all()
    )
    return [{**_version_summary(r), "is_active": r.is_active} for r in rows]


@router.get(
    "/{part_id}/config/versions/{version}",
    dependencies=[Depends(require_role("administrator"))],
)
def get_config_version(part_id: int, version: int, db: Session = Depends(get_db)):
    """One historical version's YAML and form values, for comparison."""
    _get_part(db, part_id)
    row = (
        db.query(PartConfig)
        .filter(PartConfig.part_id == part_id, PartConfig.version == version)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    return {
        **_version_summary(row),
        "is_active": row.is_active,
        "config_yaml": row.config_yaml,
        "form": form_from_config(parse_yaml(row.config_yaml)),
    }


@router.post("/{part_id}/config", status_code=201)
def create_part_config(
    part_id: int,
    payload: ConfigPayload,
    db: Session = Depends(get_db),
    user=Depends(require_role("superadministrator")),
):
    """First config for a part. Superadministrator only."""
    part = _get_part(db, part_id)
    if _active(db, part_id):
        raise HTTPException(
            status_code=409,
            detail="This part already has a config — use edit instead",
        )
    config = _save(db, part, payload, user_id=user.user_id)
    return {
        "message": "Config created",
        "config_id": config.id,
        "version": config.version,
        "config_path": config.config_path,
    }


@router.put("/{part_id}/config")
def update_part_config(
    part_id: int,
    payload: ConfigPayload,
    db: Session = Depends(get_db),
    user=Depends(require_role("administrator")),
):
    """Edit an existing config. Administrator and superadministrator.

    Saves as a new version; the current one becomes the restorable previous.
    """
    part = _get_part(db, part_id)
    if not _active(db, part_id):
        raise HTTPException(
            status_code=404,
            detail="This part has no config yet — a superadministrator must create it",
        )
    _block_if_running(db, part)
    config = _save(db, part, payload, user_id=user.user_id)
    return {
        "message": f"Config saved as version {config.version}",
        "config_id": config.id,
        "version": config.version,
        "config_path": config.config_path,
    }


@router.post("/{part_id}/config/restore-previous")
def restore_previous_config(
    part_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("administrator")),
):
    """Roll back to the version immediately before the active one.

    The restore is itself a new version rather than a deletion, so the
    history stays append-only and the bad edit remains visible.
    """
    part = _get_part(db, part_id)
    current = _active(db, part_id)
    if not current:
        raise HTTPException(status_code=404, detail="This part has no config")

    previous = _previous(db, part_id)
    if not previous:
        raise HTTPException(
            status_code=404,
            detail=(
                "There is no earlier version to restore — this config has only "
                "been saved once"
            ),
        )

    _block_if_running(db, part)

    # Rebuild rather than replay: the part's dimensions or defects may have
    # changed since, and the old YAML would carry stale tolerances.
    try:
        cfg = build_config(part, form_from_config(parse_yaml(previous.config_yaml)))
        validate_config(cfg)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Version {previous.version} is no longer valid for this part: {e}",
        )

    config = _commit_version(
        db,
        part,
        render_yaml(cfg),
        cfg,
        user_id=user.user_id,
        notes=f"Restored from version {previous.version}",
    )
    return {
        "message": f"Restored version {previous.version} as version {config.version}",
        "config_id": config.id,
        "version": config.version,
        "config_path": config.config_path,
    }