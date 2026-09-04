# OSM Indexer — spec6 Architecture Chart

Reference instantiation of the generalized `IndexerSlotTracker` using the
6000 CPR / 80-slot example config. Not a separate frozen class — a config
snapshot of the parameterized tracker.

## Config

| Param | Value |
|---|---|
| `encoder_cpr` | 6000 |
| `n_slots` | 80 |
| `heartbeats_per_slot` | 3 |
| `pulses_per_slot` (derived) | 75 |
| `heartbeat_interval` (derived) | 25 |
| `missed_heartbeat_tolerance` | 1.5 |

## Station pulse offsets

| Station | Pulse offset | Slot offset (derived) |
|---|---|---|
| S1 | 1500 | 20 |
| S2 | TBD | — |
| S3 | TBD | — |
| S4 | TBD | — |
| R1 | TBD | — |
| R2 | TBD | — |
| Exit | 4500 | 60 |

`station_slot_offset = round(pulse_offset / pulses_per_slot)`

## Pulse cadence

```
Pulse count:  0    25    50    75    100   125   150   175   ...
              |-----|-----|-----|-----|-----|-----|-----|
              HB    HB    TICK  HB    HB    TICK  HB
              (liveness check every 25 pulses)
              (slot-boundary action every 75 pulses)
```

- Every 25 pulses → `on_pulse_update()` liveness check only
- Every 75 pulses → slot boundary crossed → `tick()` fires:
  - `entry_slot_id` advances
  - part ID assigned if sensor active
  - station dispatch runs (`S1` cam flag, `R1` reject flag, `Exit` flag)

## Ring flow (per tick)

```
ENTRY ──> S1 ──> S2 ──> S3 ──> S4 ──> R1 ──> R2 ──> EXIT
(sensor)  (cam)  (cam)  (cam)  (cam)  (reject,   (log only,
                                       clears     always OK —
                                       slot on    NOK already
                                       NOK)       removed at R1)
```

- Slot table is the single source of truth (PC-side, software-only —
  motor runs continuously, no physical index-dwell)
- `part_aggregation` verdict is evaluated at **R1**, not Exit
- Missed heartbeat (gap > 25 × 1.5 = 37.5 pulses) → fault log, no action tick

## Instantiation

```python
spec6 = IndexerSlotTracker(
    encoder_cpr=6000,
    n_slots=80,
    station_pulse_offsets={"S1": 1500, "Exit": 4500},  # fill in S2-S4, R1, R2
    heartbeats_per_slot=3,
)
```

## Note

This is one part-size config, not a fixed machine spec. Large parts use
e.g. `n_slots=40`, `heartbeats_per_slot=5` (→ `pulses_per_slot=150`,
`heartbeat_interval=30`) on the same class.
