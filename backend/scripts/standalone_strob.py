import argparse
import sys
import time
from contextlib import contextmanager
from typing import Optional

from app.camera.camera_driver import CameraConnectionError
from app.camera.lucid_camera import LucidCamera
from app.config.config_loader import resolve_config_for_part
from app.plc.modbus_client import ModbusPLCClient


class StrobingCamera:
    def __init__(self, resolved_config, station_id: int):
        self.config = resolved_config
        self.station_id = station_id

        # Find the inspection station
        stations = self.config.inspection_stations()

        self.station = next(
            (
                station
                for station in stations
                if station.id == station_id
            ),
            None,
        )

        if self.station is None:
            raise ValueError(
                f"Inspection station {station_id} not found"
            )

        self.camera_id = self.station.camera_id

        # Adjust this attribute name to match your actual station config.
        self.strobe_reg: Optional[int] = self.station.strobe_reg

        self.plc = ModbusPLCClient(self.config.plc)

        self.camera = LucidCamera(
            self.camera_id,
            self.station.camera,
        )

    @contextmanager
    def fire_strobe(self):
        """
        Turn the strobe ON before capture and guarantee that
        it is turned OFF after capture.
        """
        if self.strobe_reg is None:
            print(
                f"Strobing failed for station {self.station_id}: "
                "strobe register is None"
            )
            yield
            return

        try:
            print(
                f"Strobe ON: station={self.station_id}, "
                f"register={self.strobe_reg}"
            )

            self.plc.write_register(self.strobe_reg, 1)

            # Capture happens while the strobe is ON.
            yield

        finally:
            try:
                print(
                    f"Strobe OFF: station={self.station_id}, "
                    f"register={self.strobe_reg}"
                )

                self.plc.write_register(self.strobe_reg, 0)

            except Exception as e:
                print(
                    f"Failed switching OFF register "
                    f"{self.strobe_reg} for station "
                    f"{self.station_id}: {e}"
                )

    def capture_n_infer(self, frames: int) -> None:
        try:
            self.camera.connect()

        except CameraConnectionError as e:
            print(f"Connection failed: {e}")
            return

        print(
            "connect() OK, is_connected():",
            self.camera.is_connected(),
        )

        print(f"--- capture x{frames} ---")

        try:
            for i in range(frames):
                t0 = time.perf_counter()

                # Strobe ON
                with self.fire_strobe():
                    # Capture while strobe is ON
                    frame = self.camera.read_frame()

                # Strobe OFF happens here

                elapsed_ms = (
                    time.perf_counter() - t0
                ) * 1000

                print(
                    f"frame {i + 1}/{frames}: "
                    f"shape={frame.shape} "
                    f"dtype={frame.dtype} "
                    f"min={frame.min()} "
                    f"max={frame.max()} "
                    f"mean={frame.mean():.2f} "
                    f"took={elapsed_ms:.1f}ms"
                )

        except CameraConnectionError as e:
            print(f"READ_FRAME FAILED: {e}")

        except Exception as e:
            print(f"CAPTURE FAILED: {e}")

        finally:
            print("--- close() ---")

            try:
                self.camera.close()
            except Exception as e:
                print(f"Camera close failed: {e}")

            try:
                print(
                    "is_connected() after close():",
                    self.camera.is_connected(),
                )
            except Exception as e:
                print(
                    f"is_connected() failed after close: {e}"
                )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test Lucid camera capture with PLC strobe"
    )

    parser.add_argument(
        "--part",
        required=True,
        help="Part/configuration name",
    )

    parser.add_argument(
        "--station-id",
        type=int,
        required=True,
        help="Inspection station ID",
    )

    parser.add_argument(
        "--frames",
        type=int,
        default=3,
        help="Number of frames to capture",
    )

    args = parser.parse_args()

    try:
        resolved_config = resolve_config_for_part(
            args.part
        )

        tester = StrobingCamera(
            resolved_config,
            args.station_id,
        )

        tester.capture_n_infer(args.frames)

        return 0

    except Exception as e:
        print(f"TEST FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

