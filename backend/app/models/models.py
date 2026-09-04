# backend/app/models/models.py
import hashlib
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime,
    Float, ForeignKey, Index, Integer, JSON,
    LargeBinary, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func

from app.db.db import SessionLocal


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(Text, nullable=False)
    username      = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role          = Column(Text, nullable=False)
    # operator | administrator | superadministrator
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "role IN ('operator','administrator','superadministrator')",
            name="ck_users_role",
        ),
    )

    parts        = relationship("Part", back_populates="creator")
    part_configs = relationship("PartConfig", back_populates="created_by_user")

    @staticmethod
    def _hash(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def can_login(username: str, password: str) -> Optional[dict]:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if user and User._hash(password) == user.password_hash:
                return {
                    "message":   "Login successful",
                    "role":      user.role,
                    "user_id":   user.id,
                    "user_name": user.name,
                }
            return None
        finally:
            db.close()


# ─────────────────────────────────────────────────────────────────
# CATEGORIES
# ─────────────────────────────────────────────────────────────────

class Category(Base):
    __tablename__ = "categories"

    category_id   = Column(Integer, primary_key=True, index=True)
    category_name = Column(Text, unique=True, nullable=False)

    parts = relationship("Part", back_populates="category")


# ─────────────────────────────────────────────────────────────────
# PARTS
#
# defects (JSON) — per-part defect thresholds:
#   {
#     "rust":    { "conf_thresh": 0.70, "severity": "critical", "notes": "" },
#     "crack":   { "conf_thresh": 0.65, "severity": "critical", "notes": "" },
#     "scratch": { "conf_thresh": 0.90, "severity": "minor",    "notes": "" }
#   }
#
# dimensions (JSON) — per-parameter nominal + tolerance:
#   {
#     "diameter_mm": {
#       "nominal": 25.0, "upper_limit": 26.0, "lower_limit": 24.0,
#       "unit": "mm", "notes": "shank diameter"
#     },
#     "length_mm": { ... }
#   }
#
# Pipeline config lives in PartConfig (versioned yaml), not here.
# active_config_id → points to currently active PartConfig.
# ─────────────────────────────────────────────────────────────────

class Part(Base):
    __tablename__ = "parts"

    part_id     = Column(Integer, primary_key=True, index=True)
    part_code   = Column(String(50), unique=True, nullable=False)
    part_name   = Column(Text, nullable=False)
    category_id = Column(Integer, ForeignKey("categories.category_id"), nullable=True)
    created_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    image       = Column(LargeBinary, nullable=True)
    part_weight = Column(Float, nullable=True)
    notes       = Column(Text, nullable=True)

    # ── Defect parameters ──────────────────────────────────────────
    # { class_name: { conf_thresh, severity, notes } }
    defects     = Column(JSON, nullable=True)

    # ── Measurement parameters ─────────────────────────────────────
    # { param_name: { nominal, upper_limit, lower_limit, unit, notes } }
    dimensions  = Column(JSON, nullable=True)

    # ── Pipeline flags (set when PartConfig saved) ─────────────────
    has_defect_pipeline      = Column(Boolean, default=False, nullable=False)
    has_measurement_pipeline = Column(Boolean, default=False, nullable=False)

    # ── Active config pointer ──────────────────────────────────────
    active_config_id = Column(
        Integer,
        ForeignKey("part_configs.id", use_alter=True, name="fk_parts_active_config"),
        nullable=True,
    )

    category      = relationship("Category", back_populates="parts")
    creator       = relationship("User", back_populates="parts")
    configs       = relationship(
        "PartConfig", back_populates="part", foreign_keys="PartConfig.part_id"
    )
    active_config = relationship(
        "PartConfig", foreign_keys=[active_config_id], uselist=False
    )
    sessions      = relationship("PartSession", back_populates="part")


# ─────────────────────────────────────────────────────────────────
# PART CONFIG — versioned pipeline config per part
#
# Each save from pipeline builder → new version row.
# Only one is_active=True per part at a time.
# config_yaml → full yaml stored as string (source of truth).
# config_path → /configs/{part_code}.yaml (written to disk).
# ─────────────────────────────────────────────────────────────────

class PartConfig(Base):
    __tablename__ = "part_configs"

    id          = Column(Integer, primary_key=True, index=True)
    part_id     = Column(Integer, ForeignKey("parts.part_id"), nullable=False)
    version     = Column(Integer, nullable=False, default=1)
    config_yaml = Column(Text, nullable=False)
    config_path = Column(Text, nullable=False)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    notes       = Column(Text, nullable=True)

    part             = relationship("Part", back_populates="configs", foreign_keys=[part_id])
    created_by_user  = relationship("User", back_populates="part_configs")
    sessions         = relationship("PartSession", back_populates="part_config")


# ─────────────────────────────────────────────────────────────────
# PART SESSION — one production run
#
# Links to exact PartConfig version active at session start.
# Counters (total_fired, total_passed, total_failed) updated
# incrementally after each station fire — avoids COUNT() queries.
# ─────────────────────────────────────────────────────────────────

class PartSession(Base):
    __tablename__ = "part_sessions"

    id             = Column(Integer, primary_key=True, index=True)
    part_id        = Column(Integer, ForeignKey("parts.part_id"), nullable=False)
    part_config_id = Column(Integer, ForeignKey("part_configs.id"), nullable=False)

    # Denormalized for fast reads
    part_code      = Column(String(50), nullable=False)
    part_name      = Column(Text, nullable=False)

    station_id     = Column(String(50), nullable=False, default="s1")
    station_type   = Column(Text, nullable=False, default="inspection")
    # inspection | counting
    station_source = Column(Text, nullable=False, default="simulation")
    # simulation | plc | ui_button

    order_no       = Column(String(50), nullable=True)
    target_count   = Column(Integer, nullable=True)
    notes          = Column(Text, nullable=True)

    # Live counters — incremented after each station fire
    total_fired    = Column(Integer, default=0, nullable=False)
    total_passed   = Column(Integer, default=0, nullable=False)
    total_failed   = Column(Integer, default=0, nullable=False)

    session_start  = Column(DateTime(timezone=True), server_default=func.now())
    session_end    = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "station_type IN ('inspection','counting')",
            name="ck_session_station_type",
        ),
        CheckConstraint(
            "station_source IN ('simulation','plc','ui_button')",
            name="ck_session_station_source",
        ),
    )

    part        = relationship("Part", back_populates="sessions")
    part_config = relationship("PartConfig", back_populates="sessions")
    results     = relationship("SessionResult", back_populates="session")


# ─────────────────────────────────────────────────────────────────
# SESSION RESULT — one row per station fire
#
# station_fire_no → sequential within session (1, 2, 3 …)
# overall_passed  → aggregated across all cameras in this station's own
#                    stations — EXCEPT on the exit/reject-station row (see
#                    station_id below), where it is the part's final
#                    aggregated OK/NOK per part_aggregation.pass_if.
#
# station_id   → which station produced this row ("s1" / "s2" / "exit1"),
#                matches machine_config.yaml's stations[].id. A part with
#                multiple inspection stations produces multiple rows.
#
# ring_part_id → IndexerSlotTracker's per-part identifier
#                (SlotRecord.assign_part_id). Ties together every row
#                belonging to the same physical part as it crosses
#                s1 -> s2 -> exit/reject — assigned when the part
#                enters, lives with it until it exits or is rejected
#                (IndexerSlotTracker.free_slot()). Query all rows for one
#                (session_id, ring_part_id) to get a part's full station
#                history and evaluate the exit/reject aggregation.
#
# rejected     → final reject flag, set only on the exit/reject-station row.
#                True = physically discarded via the blower (CLAUDE.md
#                Rule 3). Null on s1/s2 rows — the decision hasn't
#                been made there.
# ─────────────────────────────────────────────────────────────────

class SessionResult(Base):
    __tablename__ = "session_results"

    id              = Column(Integer, primary_key=True, index=True)
    session_id      = Column(Integer, ForeignKey("part_sessions.id"), nullable=False)
    station_id      = Column(String(50), nullable=False)
    ring_part_id    = Column(Integer, nullable=False, index=True)
    station_fire_no = Column(Integer, nullable=False)
    fired_at        = Column(DateTime(timezone=True), server_default=func.now())
    overall_passed  = Column(Boolean, nullable=True)
    rejected        = Column(Boolean, nullable=True)
    plc_written     = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_session_results_session_ring_part", "session_id", "ring_part_id"),
    )

    session        = relationship("PartSession", back_populates="results")
    camera_results = relationship("CameraResult", back_populates="session_result")


# ─────────────────────────────────────────────────────────────────
# CAMERA RESULT — one row per camera per station fire
#
# detection_bbox (JSON):
#   { x1, y1, x2, y2, confidence, class_name }
#   from object_detection step — null if no obj_detection in pipeline
#
# all_detections (JSON):
#   [ { class_name, confidence, bbox: [x1,y1,x2,y2] }, ... ]
#   from defect_detection step
#
# measurement_data (JSON):
#   {
#     "diameter_mm": {
#       "nominal": 25.0, "upper_limit": 26.0, "lower_limit": 24.0,
#       "measured": 25.3, "deviation": 0.3, "passed": true, "unit": "mm"
#     },
#     "length_mm": { ... }
#   }
#   calibration_factor applied per-parameter before comparison
# ─────────────────────────────────────────────────────────────────

class CameraResult(Base):
    __tablename__ = "camera_results"

    id                = Column(Integer, primary_key=True, index=True)
    session_result_id = Column(Integer, ForeignKey("session_results.id"), nullable=False)
    camera_id         = Column(String(50), nullable=False)
    pipeline_name     = Column(String(50), nullable=False, default="pipeline1")
    captured_at       = Column(DateTime(timezone=True), server_default=func.now())

    # Object detection step output
    detection_bbox    = Column(JSON, nullable=True)

    # Defect detection step output
    is_defective      = Column(Boolean, nullable=True)
    defect_label      = Column(Text, nullable=True)
    defect_confidence = Column(Float, nullable=True)
    all_detections    = Column(JSON, nullable=True)

    # Measurement step output
    measurement_data   = Column(JSON, nullable=True)
    measurement_passed = Column(Boolean, nullable=True)

    # Overall camera result
    camera_passed    = Column(Boolean, nullable=True)
    annotated_image  = Column(LargeBinary, nullable=True)

    session_result = relationship("SessionResult", back_populates="camera_results")
