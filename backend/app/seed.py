"""Idempotent demo-data seed: 2 rubber parts with measurement + defect config.

Run via: python -m app.seed
Safe to re-run — matches on part_code, updates in place instead of duplicating.
"""
import yaml

from app.db.db import SessionLocal
from app.models.models import Category, Part, PartConfig

CATEGORY_NAME = "Rubber"

DEMO_PARTS: list[dict] = [
    {
        "part_code": "RS-001",
        "part_name": "Rubber Small",
        "dimensions": {
            "OD": {
                "nominal": 10.0,
                "upper_limit": 10.2,
                "lower_limit": 9.8,
                "unit": "mm",
                "notes": "station_1 measurement",
            },
        },
        "defects": {
            "thread": {"conf_thresh": 0.5, "severity": "critical", "notes": ""},
            "air": {"conf_thresh": 0.7, "severity": "critical", "notes": ""},
        },
    },
    {
        "part_code": "RB-001",
        "part_name": "Rubber Big",
        "dimensions": {
            "OD": {
                "nominal": 10.0,
                "upper_limit": 10.2,
                "lower_limit": 9.8,
                "unit": "mm",
                "notes": "station_1 measurement",
            },
        },
        "defects": {
            "thread": {"conf_thresh": 0.5, "severity": "critical", "notes": ""},
            "air": {"conf_thresh": 0.7, "severity": "critical", "notes": ""},
        },
    },
]

MODE_OF_OPERATION = "Measurement & Defect Detection"


def build_config_yaml(part_code: str, dimensions: dict, defects: dict) -> str:
    station_config = {
        "mode_of_operation": MODE_OF_OPERATION,
        "station_1": {
            "type": "measurement",
            "parameter": "OD",
            "nominal": dimensions["OD"]["nominal"],
            "min_tolerance": dimensions["OD"]["lower_limit"],
            "max_tolerance": dimensions["OD"]["upper_limit"],
            "confidence_threshold": 0.8,
        },
        "station_2": {
            "type": "defect_detection",
            "defects": {
                name: {"confidence_threshold": spec["conf_thresh"]}
                for name, spec in defects.items()
            },
        },
    }
    return yaml.safe_dump(station_config, sort_keys=False)


def upsert_category(db, name: str) -> Category:
    category = db.query(Category).filter_by(category_name=name).first()
    if category is None:
        category = Category(category_name=name)
        db.add(category)
        db.flush()
    return category


def upsert_part(db, category: Category, spec: dict) -> Part:
    part = db.query(Part).filter_by(part_code=spec["part_code"]).first()
    if part is None:
        part = Part(part_code=spec["part_code"], part_name=spec["part_name"])
        db.add(part)

    part.part_name = spec["part_name"]
    part.category_id = category.category_id
    part.dimensions = spec["dimensions"]
    part.defects = spec["defects"]
    part.has_measurement_pipeline = True
    part.has_defect_pipeline = True
    db.flush()
    return part


def upsert_part_config(db, part: Part, config_yaml: str, config_path: str) -> PartConfig:
    config = (
        db.query(PartConfig)
        .filter_by(part_id=part.part_id, is_active=True)
        .first()
    )
    if config is None:
        config = PartConfig(
            part_id=part.part_id,
            version=1,
            config_yaml=config_yaml,
            config_path=config_path,
            is_active=True,
        )
        db.add(config)
    else:
        config.config_yaml = config_yaml
        config.config_path = config_path

    db.flush()
    part.active_config_id = config.id
    return config


def seed() -> None:
    db = SessionLocal()
    try:
        category = upsert_category(db, CATEGORY_NAME)

        for spec in DEMO_PARTS:
            part = upsert_part(db, category, spec)
            config_yaml = build_config_yaml(
                spec["part_code"], spec["dimensions"], spec["defects"]
            )
            config_path = f"seed/{spec['part_code']}.yaml"
            upsert_part_config(db, part, config_yaml, config_path)

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
