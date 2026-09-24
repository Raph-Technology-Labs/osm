"""Read-only PLC monitor: is the encoder moving, and does the part sensor fire?

The digital twin and every station trigger are driven by two PLC registers:
encoder_indexer_ppr (disc position, 0..encoder_cpr per revolution) and
part_sensor (part detected at entry). If the twin doesn't move or cameras
never fire, run this next to the backend while the motor runs and parts are
loaded -- it shows which of the two the PC isn't seeing.

It only READS registers (one batch per sample); it never writes, so it's safe
to run alongside a live session. Addresses and PLC IP come from the same
machine_config.yaml the backend uses.

Usage (from backend/):
    python scripts/plc_monitor.py              # 15 s at 20 Hz
    python scripts/plc_monitor.py --seconds 30 --hz 10
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.config_loader import load_machine_config, resolve_config_for_part  # noqa: E402
from app.plc.modbus_client import ModbusPLCClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--hz", type=float, default=20.0)
    args = ap.parse_args()

    cfg = resolve_config_for_part(load_machine_config()["machine"]["part_code"])
    regs = cfg.plc.registers
    cpr = cfg.indexer.encoder_cpr
    names = {
        "pulse_count": regs.pulse_count,
        "encoder_indexer_ppr": regs.encoder_indexer_ppr,
        "part_sensor": regs.part_sensor,
        "heartbeat": regs.heartbeat,
    }
    start = min(names.values())
    count = max(names.values()) - start + 1

    plc = ModbusPLCClient(cfg.plc)
    print(f"PLC {cfg.plc.ip}:{cfg.plc.port}  reading {start}..{start + count - 1}  "
          f"encoder_cpr={cpr}  ({args.seconds:g}s at {args.hz:g} Hz, read-only)")
    try:
        plc.connect()
    except Exception as e:  # noqa: BLE001
        print(f"CANNOT CONNECT to PLC: {e}")
        return 1

    first = last = None
    fwd = back = 0
    edges = 0
    samples = 0
    read_ms: list[float] = []
    t_end = time.monotonic() + args.seconds
    try:
        while time.monotonic() < t_end:
            t0 = time.perf_counter()
            try:
                vals = plc.read_registers(start, count)
            except Exception as e:  # noqa: BLE001
                print(f"  read failed: {e}")
                time.sleep(1 / args.hz)
                continue
            read_ms.append((time.perf_counter() - t0) * 1000)
            v = {k: vals[a - start] for k, a in names.items()}
            samples += 1
            enc = v["encoder_indexer_ppr"]
            changed = []
            if last is not None:
                d = (enc - last["encoder_indexer_ppr"]) % cpr
                if d and d <= cpr // 2:
                    fwd += d
                elif d:
                    back += cpr - d
                    changed.append(f"BACK {cpr - d}")
                if v["part_sensor"] and not last["part_sensor"]:
                    edges += 1
                    changed.append("PART SENSOR ON")
                elif not v["part_sensor"] and last["part_sensor"]:
                    changed.append("part sensor off")
            if last is None or changed or samples % int(max(args.hz, 1)) == 0:
                print(f"  t={args.seconds - (t_end - time.monotonic()):5.1f}s  "
                      f"ppr={enc:5d}  pulse_count={v['pulse_count']:6d}  "
                      f"part_sensor={v['part_sensor']}  heartbeat={v['heartbeat']:5d}  "
                      f"{'  '.join(changed)}")
            first = first or v
            last = v
            time.sleep(max(0.0, 1 / args.hz - (time.perf_counter() - t0)))
    finally:
        plc.close()

    if not samples:
        print("No successful reads.")
        return 1
    rpm = fwd / cpr / args.seconds * 60
    read_ms.sort()
    print("\nSUMMARY")
    print(f"  samples: {samples}, Modbus read time median {read_ms[len(read_ms) // 2]:.1f} ms, "
          f"max {read_ms[-1]:.1f} ms")
    print(f"  encoder forward: {fwd} counts (~{rpm:.1f} rpm), backward: {back} counts")
    print(f"  part_sensor rising edges: {edges}")
    print(f"  heartbeat: {first['heartbeat']} -> {last['heartbeat']}")
    print("\nREADING IT")
    if fwd < cpr * 0.05:
        print("  - Encoder is (almost) NOT moving -> twin can't move. Check the motor is really "
              "running (Start motor pressed? speed_setpoint written?) and the encoder wiring/PLC "
              "program for encoder_indexer_ppr.")
    else:
        print("  - Encoder moves fine.")
    if edges == 0:
        print("  - Part sensor NEVER turned on -> no part ever enters the twin, so no camera "
              "fires. Check the sensor LED when a part passes, its wiring to the PLC, and that "
              f"the PLC copies it to register {regs.part_sensor}.")
    else:
        print(f"  - Part sensor fired {edges}x -> parts should enter the twin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
