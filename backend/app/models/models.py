from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    Boolean,
    DateTime,
    CheckConstraint,
    Float,
    JSON,
    LargeBinary
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ==========================================================
# USERS
# ==========================================================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    username = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(Text, nullable=False)

    parts = relationship("Part", back_populates="creator")


# ==========================================================
# CATEGORIES
# ==========================================================
class Category(Base):
    __tablename__ = "categories"

    category_id = Column(Integer, primary_key=True, index=True)
    category_name = Column(Text, unique=True, nullable=False)

    parts = relationship("Part", back_populates="category")


# ==========================================================
# PARTS (UNCHANGED)
# ==========================================================
class Part(Base):
    __tablename__ = "parts"

    part_id = Column(Integer, primary_key=True, index=True)
    part_code = Column(String(50), unique=True, nullable=False)
    part_name = Column(Text, nullable=False)

    category_id = Column(Integer, ForeignKey("categories.category_id"))
    created_by = Column(Integer, ForeignKey("users.id"))

    parts_metadata = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    image = Column(LargeBinary)

    part_weight = Column(Float)
    part_height = Column(Float)
    part_width = Column(Float)
    part_diameter = Column(Float)

    plc_speed_factor_feeder1 = Column(Float, server_default="1.0")
    plc_speed_factor_feeder2 = Column(Float, server_default="1.0")
    plc_speed_factor_hopper = Column(Float, server_default="1.0")
    plc_gate_hopper_opening_factor = Column(Float, server_default="1.0")

    plain_primary = Column(Float, server_default="1.0")
    plain_secondary = Column(Float, server_default="1.0")
    corrugated_primary = Column(Float, server_default="1.0")
    corrugated_secondary = Column(Float, server_default="1.0")

    category = relationship("Category", back_populates="parts")
    creator = relationship("User", back_populates="parts")
    sessions = relationship("CompanySession", back_populates="part")

    operation_modes = relationship("PartOperationMode", back_populates="part")
    defects = relationship("PartDefect", back_populates="part")
    measurement_configs = relationship(
        "PartMeasurementConfig",
        back_populates="part"
    )


# ==========================================================
# COMPANY SESSIONS (UNCHANGED)
# ==========================================================
class CompanySession(Base):
    __tablename__ = "company_sessions"

    id = Column(Integer, primary_key=True, index=True)

    part_id = Column(Integer, ForeignKey("parts.part_id"))
    part_code = Column(String(50), nullable=False)
    part_name = Column(Text, nullable=False)

    mode = Column(Text, nullable=False)
    batching_mode = Column(Text, nullable=False, server_default="auto")

    no_of_batches = Column(Integer)
    batch_delay = Column(Integer)
    number_of_parts_per_batches = Column(Integer)

    part_count = Column(Integer, nullable=False)
    batch_counts = Column(JSON)

    parts_per_minute = Column(Integer)

    session_start = Column(DateTime(timezone=True), server_default=func.now())
    session_end = Column(DateTime(timezone=True))

    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session_weight = Column(Float)
    order_no = Column(String(50))

    counting_type = Column(String(50))  # 'Conveyor' | 'GCM' | 'SCM' | 'Batch' | 'Bulk' — only set when mode == 'Counting'

    is_calibration = Column(Boolean, default=False)

    calibration_expected_per_run = Column(Integer)
    calibration_total_runs = Column(Integer)
    calibration_runs = Column(JSON)

    calibration_avg_count = Column(Float)
    calibration_avg_accuracy = Column(Float)

    calibration_passed = Column(Boolean)

    calibration_completed_at = Column(DateTime(timezone=True))

    part = relationship("Part", back_populates="sessions")

    defects = relationship("PartDefect", back_populates="session")
    measurements = relationship(
        "SessionMeasurement",
        back_populates="session"
    )


# ==========================================================
# SCM → PART OPERATION MODES
# ==========================================================
class PartOperationMode(Base):
    __tablename__ = "part_operation_modes"

    id = Column(Integer, primary_key=True)

    part_id = Column(
        Integer,
        ForeignKey("parts.part_id", ondelete="CASCADE"),
        nullable=False
    )

    mode_of_operation = Column(String(100), nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "mode_of_operation IN ("
            "'Counting', "
            "'Defect Detection', "
            "'Measurement', "
            "'Measurement & Defect Detection'"
            ")",
            name="operation_mode_check"
        ),
    )

    part = relationship("Part", back_populates="operation_modes")


# ==========================================================
# SCM → DEFECT TABLE
# ==========================================================
class PartDefect(Base):
    __tablename__ = "part_defects"

    id = Column(Integer, primary_key=True)

    session_id = Column(
        Integer,
        ForeignKey("company_sessions.id", ondelete="CASCADE")
    )
    part_id = Column(
        Integer,
        ForeignKey("parts.part_id", ondelete="CASCADE")
    )

    # config-driven — any defects from machine_config.yaml land here
    # e.g. {"rust": 3, "scratch": 1, "crack": 0, "thread_missing": 2}
    defects_data = Column(JSON, nullable=False, default=dict)

    # which camera captured this
    cam_id = Column(String(50))          # "cam1", "cam2"
    trigger_id = Column(String(50))      # "trigger1"

    # overall result for this inspection
    part_ok = Column(Boolean, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("CompanySession", back_populates="defects")
    part = relationship("Part", back_populates="defects")

# ==========================================================
# SCM → MASTER MEASUREMENT CONFIG (= Master / expected values (what the part should be)
# ==========================================================
class PartMeasurementConfig(Base):
    __tablename__ = "part_measurement_configs"

    id = Column(Integer, primary_key=True)

    part_id = Column(
        Integer,
        ForeignKey("parts.part_id", ondelete="CASCADE")
    )

    actual_measurement_data = Column(JSON)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    part = relationship("Part", back_populates="measurement_configs")


# ==========================================================
# SCM → SESSION LIVE MEASUREMENTS (= Actual measured values from machine during runtime (what the machine detected)
# ==========================================================
class SessionMeasurement(Base):
    __tablename__ = "session_measurements"

    id = Column(Integer, primary_key=True)

    session_id = Column(
        Integer,
        ForeignKey("company_sessions.id", ondelete="CASCADE")
    )

    measured_realtime_data = Column(JSON)

    overall_status = Column(
        String(20),
        CheckConstraint(
            "overall_status IN ('OK', 'NOK')"
        )
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    session = relationship("CompanySession", back_populates="measurements")