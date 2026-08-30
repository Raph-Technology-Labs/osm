import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.seed as seed_module
from app.models.models import Base, Category, Part, PartConfig


@pytest.fixture()
def isolated_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(seed_module, "SessionLocal", test_session_local)
    return test_session_local


def test_seed_is_idempotent_and_correct(isolated_db):
    seed_module.seed()
    seed_module.seed()  # rerun should not duplicate anything

    db = isolated_db()
    try:
        categories = db.query(Category).all()
        assert len(categories) == 1
        assert categories[0].category_name == "Rubber"

        parts = db.query(Part).all()
        assert len(parts) == 2
        assert {p.part_code for p in parts} == {"RS-001", "RB-001"}

        configs = db.query(PartConfig).all()
        assert len(configs) == 2  # exactly one active config per part

        rs = db.query(Part).filter_by(part_code="RS-001").first()
        assert rs.part_name == "Rubber Small"
        assert rs.category_id == categories[0].category_id
        assert rs.has_measurement_pipeline is True
        assert rs.has_defect_pipeline is True
        assert rs.dimensions["OD"] == {
            "nominal": 10.0,
            "upper_limit": 10.2,
            "lower_limit": 9.8,
            "unit": "mm",
            "notes": "station_1 measurement",
        }
        assert rs.defects["thread"]["conf_thresh"] == 0.5
        assert rs.defects["air"]["conf_thresh"] == 0.7

        rb = db.query(Part).filter_by(part_code="RB-001").first()
        assert rb.part_name == "Rubber Big"

        rs_config = db.query(PartConfig).filter_by(part_id=rs.part_id).first()
        assert rs.active_config_id == rs_config.id
        assert rs_config.is_active is True
        assert rs_config.version == 1
        assert "mode_of_operation: Measurement & Defect Detection" in rs_config.config_yaml
        assert "station_1" in rs_config.config_yaml
        assert "station_2" in rs_config.config_yaml
    finally:
        db.close()


def test_seed_updates_existing_part_instead_of_duplicating(isolated_db):
    seed_module.seed()

    db = isolated_db()
    try:
        rs = db.query(Part).filter_by(part_code="RS-001").first()
        rs.part_name = "Manually Edited Name"
        db.commit()
    finally:
        db.close()

    seed_module.seed()  # should overwrite the manual edit, not add a row

    db = isolated_db()
    try:
        matches = db.query(Part).filter_by(part_code="RS-001").all()
        assert len(matches) == 1
        assert matches[0].part_name == "Rubber Small"
    finally:
        db.close()
