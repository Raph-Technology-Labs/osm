# Spec 2 — Simulator / Mock Hardware Sources

## Context

The tower's PLC and cameras won't always be available during development. Rather than testing against a reduced/fake topology, the app always uses the real (eventual) machine topology from `default_config.yaml` — `sim.enabled` decides where each device's data comes from, not how many devices the app thinks exist. This spec builds the mock sources; wiring them into the actual polling threads is spec 3.

Read `specs/08_session_config_lifecycle.md` section 1a before starting. Read `CLAUDE.md` for project context.

**Process: present a plan first (files to add/change, function signatures, no full implementations) and wait for confirmation before writing code.**

## Existing files relevant to this task

- `backend/app/schemas/machine_config.py` (from spec 1) — `MachineConfig`, `Station`, `Camera` shapes to match against.
- `backend/app/core/config_loader.py` (from spec 1) — `load_machine_config()`.

## What to build

**New files:**
- `backend/app/hardware/plc_interface.py` — an abstract interface (`Protocol` or ABC) both the real and mock PLC clients implement: `connect()`, `read_registers() -> dict`, `write_actuator(name: str, value) -> None`, `disconnect()`.
- `backend/app/hardware/plc_sim.py` — `PLCSimClient` implementing `plc_interface`. Simulates encoder tick increments over time, exposes a fixed set of example registers, accepts (and logs, no-ops) actuator writes.
- `backend/app/hardware/camera_interface.py` — abstract interface both real (Arena SDK) and mock camera sources implement: `connect()`, `capture_frame() -> Frame`, `disconnect()`. `Frame` can be a simple dataclass wrapping raw bytes + metadata for now — real Arena SDK wrapper is a separate, later task, not part of this spec.
- `backend/app/hardware/camera_sim.py` — `MockCameraSource` implementing `camera_interface`. Cycles through a small folder of sample images (add 3–5 placeholder images under `backend/app/hardware/sample_frames/`) per configured camera ID, returning a different sample frame each call in rotation.
- `backend/app/hardware/device_resolver.py`:
  - `get_plc_client(machine_config: MachineConfig) -> PLCInterface` — returns `PLCSimClient` if `machine_config.sim.enabled` is true (or the PLC-specific override, if the schema supports one), otherwise returns the real client (stub this out — real implementation is a later task, raise `NotImplementedError` for now if `sim.enabled=false`).
  - `get_camera_source(camera_id: str, machine_config: MachineConfig) -> CameraInterface` — same pattern, per-camera: checks a per-camera `sim` override if present, falling back to the global `sim.enabled` default. Returns `MockCameraSource` for sim, stubs real Arena SDK wrapper for non-sim.

**Behavior:**
- Every mock source must return data in the exact same shape the real source will — this is the whole point, so downstream code (polling threads, pipeline dispatch) never needs to know or care whether it's real or simulated.
- Support **mixed real/sim**: if the schema in `machine_config.yaml` allows a per-camera `sim` override (confirm this exists per spec 1's schema — if not, flag it as a gap to fix in spec 1 rather than duplicating the field definition here), a camera can be real while others are simulated, for partial-hardware commissioning.

**Tests:**
- `test_plc_sim_returns_incrementing_ticks`
- `test_plc_sim_accepts_actuator_write_without_error`
- `test_mock_camera_cycles_through_sample_frames`
- `test_device_resolver_returns_sim_client_when_enabled`
- `test_device_resolver_returns_per_camera_override`

## Explicitly out of scope for this spec

- The real Arena SDK camera wrapper and real Modbus/pymodbus PLC client — stub with `NotImplementedError`, do not implement
- The polling threads that call these interfaces continuously — that's spec 3
- Any change to `machine_config.yaml`'s schema beyond confirming/adding the `sim` override field structure from spec 1 if it's missing

## Definition of done

- `pytest` passes all tests listed above
- `get_plc_client()` and `get_camera_source()` correctly switch between sim/real based on config, without any caller code needing an `if sim` branch
- Calling `MockCameraSource.capture_frame()` repeatedly returns different sample images in rotation, never crashes on the Nth call
- No changes to files outside what's listed above
