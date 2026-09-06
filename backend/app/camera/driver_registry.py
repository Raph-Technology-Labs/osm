"""Camera vendor name (machine_config.yaml's cameras.<id>.vendor) -> driver
class. Adding a new camera make: implement CameraDriver (camera_driver.py),
register it here, done -- station_registry.py/inspection_session.py never
need to change, they only ever ask for get_driver_class(camera_config.vendor).
"""

from typing import Dict, Type

from app.camera.camera_driver import CameraDriver
from app.camera.lucid_camera import LucidCamera

CAMERA_DRIVERS: Dict[str, Type[CameraDriver]] = {
    "lucid": LucidCamera,
    "arena": LucidCamera,  # alias: "Arena" is the SDK's name, Lucid is the camera vendor
}


def get_driver_class(vendor: str) -> Type[CameraDriver]:
    try:
        return CAMERA_DRIVERS[vendor]
    except KeyError:
        raise ValueError(
            f"Unknown camera vendor {vendor!r} -- registered drivers: {sorted(CAMERA_DRIVERS)}"
        ) from None
