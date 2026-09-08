"""StationDispatcher real-hardware-mode (spec12) unit tests -- real
IndexerSlotTracker, a fake ModbusPLCClient (queued register reads / logged
writes), a fake resolved_config exposing the fields _tick_real() actually
touches (.plc.registers, .plc.real_poll_interval_ms, .plc.sim.
entry_sensor_response_delay_ms/.reject_actuator_response_delay_ms --
ring-wide, not per-station, per explicit instruction 2026-09-08 --
.indexer.entry_sensor_mid_offset_pulses, and a reject station's
.station_offset_pulses).

Ticks are invoked directly (dispatcher._tick_real()), not through the real
threading.Timer loop -- _schedule_tick() is stubbed to a no-op so tests are
deterministic and don't need real sleeps or timing margins.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.indexer.dispatcher import PULSE_COUNT_REGISTER_WRAP, StationDispatcher
from app.indexer.tracker import IndexerSlotTracker

PULSE_COUNT_REG = 40001
PART_SENSOR_REG = 40004
REJECT_CMD_REG = 40009


@dataclass
class FakeRegisters:
    pulse_count: int = PULSE_COUNT_REG
    part_sensor: int = PART_SENSOR_REG
    reject_cmd: int = REJECT_CMD_REG


@dataclass
class FakeIndexerConfig:
    entry_sensor_mid_offset_pulses: int = 0


@dataclass
class FakeRealPlcSim:
    enabled: bool = False
    # Ring-wide (not per-station) real-hardware timing corrections -- moved
    # here from indexer/the reject station per explicit instruction
    # 2026-09-08, see PLCSimConfig in config_loader.py.
    entry_sensor_response_delay_ms: float = 0.0
    reject_actuator_response_delay_ms: float = 0.0


@dataclass
class FakeRealPlc:
    sim: FakeRealPlcSim = field(default_factory=FakeRealPlcSim)
    registers: FakeRegisters = field(default_factory=FakeRegisters)
    real_poll_interval_ms: float = 20.0


@dataclass
class FakeRejectStation:
    id: str = "r1"
    type: str = "reject"
    enabled: bool = True
    station_offset_pulses: int = 0


@dataclass
class FakeInspectionStation:
    id: str
    type: str = "inspection"


class FakeRealResolvedConfig:
    def __init__(self, stations, indexer=None, plc=None):
        self.stations = stations
        self.indexer = indexer or FakeIndexerConfig()
        self.plc = plc or FakeRealPlc()

    def inspection_stations(self):
        return [s for s in self.stations if s.type == "inspection"]

    def reject_station(self):
        for s in self.stations:
            if s.type == "reject":
                return s
        return None


class FakeStationRegistry:
    def __init__(self):
        self.fired: List[str] = []

    def fire_station(self, station_id: str, slot_id=None, part_id=None) -> None:
        self.fired.append(station_id)


class FakePlcClient:
    """Queued reads per register, keyed by register number (not call order),
    so pulse_count and part_sensor can be driven independently."""

    def __init__(self):
        self.queues: Dict[int, list] = {}
        self.writes: List[tuple] = []

    def queue(self, reg: int, values: list) -> None:
        self.queues.setdefault(reg, []).extend(values)

    def read_register(self, reg: int) -> int:
        q = self.queues[reg]
        return int(q.pop(0))

    def write_register(self, reg: int, value: int) -> None:
        self.writes.append((reg, value))


def make_real_dispatcher(
    n_slots=10,
    encoder_cpr=100,
    reject_station: Optional[FakeRejectStation] = None,
    indexer: Optional[FakeIndexerConfig] = None,
    plc: Optional[FakeRealPlc] = None,
):
    stations = [FakeInspectionStation(id="s1")]
    if reject_station is not None:
        stations.append(reject_station)
    config = FakeRealResolvedConfig(stations, indexer=indexer, plc=plc)
    tracker = IndexerSlotTracker(
        n_slots=n_slots,
        encoder_cpr=encoder_cpr,
        station_pulse_offsets={"s1": 0} if reject_station is None else {"s1": 0, "r1": 0},
        inspection_station_ids=["s1"],
    )
    registry = FakeStationRegistry()
    plc_client = FakePlcClient()
    dispatcher = StationDispatcher(config, registry, tracker, plc_client=plc_client)
    # Drive _tick_real() directly and deterministically -- no real timer.
    dispatcher._stopped = False
    dispatcher._schedule_tick = lambda: None
    return dispatcher, tracker, plc_client


def test_rising_edge_derives_slot_index_and_stores_pulse_count_at_detection():
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100)
    plc.queue(PULSE_COUNT_REG, [55, 63])
    plc.queue(PART_SENSOR_REG, [False, True])

    dispatcher._tick_real()  # baseline reading, no edge
    dispatcher._tick_real()  # rising edge: accumulated = 63-55 = 8

    slot_index = (8 // tracker.pulses_per_slot) % tracker.n_slots
    record = tracker.get_slot(slot_index)
    assert record.assign_part_id is not None
    assert record.pulse_count_at_detection == 8


def test_level_high_across_ticks_counts_once_not_per_tick():
    # Edge, not level: the first True reading legitimately counts as a
    # rising edge (no known prior state), but the sensor staying high on
    # subsequent polls must not re-trigger -- one part in, not three.
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100)
    plc.queue(PULSE_COUNT_REG, [10, 20, 30])
    plc.queue(PART_SENSOR_REG, [True, True, True])

    dispatcher._tick_real()  # rising edge (False -> True): one part enters
    dispatcher._tick_real()  # still True: no re-trigger
    dispatcher._tick_real()  # still True: no re-trigger

    assert tracker.in_flight_count == 1


def test_target_fire_pulse_reflects_actual_detected_offset_not_nominal_slot():
    # Two mocked detections at slightly different pulse offsets for the
    # same slot_index (across "two revolutions") must produce different
    # target_fire_pulse values -- acceptance criterion.
    reject = FakeRejectStation(station_offset_pulses=50)
    dispatcher, tracker, _plc = make_real_dispatcher(n_slots=10, encoder_cpr=100, reject_station=reject)

    # Slot 3 entered at pulse 33 (revolution 1)
    tracker.on_part_entered(33, part_id="A")
    tracker.mark_pending(3, "s1")
    tracker.apply_station_result(3, "s1", passed=False)  # nok

    # Slot 3 (physically) entered again one revolution later at pulse 137
    # (137 // 10 % 10 == 3, same slot, different detected offset)
    tracker.free_slot(3)
    tracker.on_part_entered(137, part_id="B")
    tracker.mark_pending(3, "s1")
    tracker.apply_station_result(3, "s1", passed=False)

    dispatcher._arm_reject_targets(reject)
    target_second = dispatcher._pending_reject_targets[3]
    assert target_second == 137 + 50  # corrected_detection + station_offset_pulses, zero delays

    # Confirm a different detected offset really does produce a different
    # target (not the nominal slot boundary in both cases).
    dispatcher._pending_reject_targets.clear()
    tracker.free_slot(3)
    tracker.on_part_entered(33, part_id="C")
    tracker.mark_pending(3, "s1")
    tracker.apply_station_result(3, "s1", passed=False)
    dispatcher._arm_reject_targets(reject)
    target_first = dispatcher._pending_reject_targets[3]

    assert target_first != target_second
    assert target_first == 33 + 50


def test_wraparound_crossing_between_detection_and_fire():
    # pulse_count wraps (65535 -> 0-ish) between when a target is armed and
    # when it's actually reached -- the monotonic accumulator must keep
    # counting up through the wrap, not corrupt/reset the pending target.
    reject = FakeRejectStation(station_offset_pulses=10)
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=1000, encoder_cpr=100000, reject_station=reject)

    near_wrap = PULSE_COUNT_REGISTER_WRAP - 5
    plc.queue(PULSE_COUNT_REG, [near_wrap, near_wrap, 3, 20])  # wraps between samples 2 and 3
    plc.queue(PART_SENSOR_REG, [False, True, False, False])

    dispatcher._tick_real()  # baseline
    dispatcher._tick_real()  # rising edge at accumulated=0 (first real gap after baseline)
    slot_index = 0
    record = tracker.get_slot(slot_index)
    assert record.assign_part_id is not None
    tracker.mark_pending(slot_index, "s1")
    tracker.apply_station_result(slot_index, "s1", passed=False)

    dispatcher._tick_real()  # crosses the 65536 boundary: gap = (65536-65531)+3 = 8
    assert dispatcher._real_accumulated_pulses == 8  # monotonic, kept counting through the wrap

    target = dispatcher._pending_reject_targets[slot_index]
    assert target == 0 + 10  # detection was at accumulated=0

    dispatcher._tick_real()  # gap = 20-3 = 17 -> accumulated = 25, past target=10
    assert slot_index not in dispatcher._pending_reject_targets
    assert (REJECT_CMD_REG, 1) in plc.writes
    assert (REJECT_CMD_REG, 0) in plc.writes
    assert tracker.get_slot(slot_index).assign_part_id is None
    assert tracker.r1_removed == 1


def test_speed_scale_change_does_not_corrupt_pending_target():
    reject = FakeRejectStation(station_offset_pulses=10)
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100, reject_station=reject)
    plc.queue(PULSE_COUNT_REG, [0, 5])
    plc.queue(PART_SENSOR_REG, [False, True])

    dispatcher._tick_real()
    dispatcher._tick_real()  # part enters at accumulated=5
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)
    dispatcher._arm_reject_targets(reject)
    target_before = dispatcher._pending_reject_targets[0]

    # speed_scale only affects _tick_sim's synthetic advance -- changing it
    # mid-session in real mode must be a no-op for reject-timing math.
    dispatcher.set_speed_scale(5.0)

    dispatcher._pending_reject_targets.clear()
    dispatcher._arm_reject_targets(reject)
    assert dispatcher._pending_reject_targets[0] == target_before


def test_fire_and_immediately_clear_not_hold_then_clear():
    reject = FakeRejectStation(station_offset_pulses=0)
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100, reject_station=reject)
    plc.queue(PULSE_COUNT_REG, [0, 5])
    plc.queue(PART_SENSOR_REG, [False, True])

    dispatcher._tick_real()
    dispatcher._tick_real()
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)

    plc.queue(PULSE_COUNT_REG, [5])
    plc.queue(PART_SENSOR_REG, [False])
    dispatcher._tick_real()  # arms (target=5) and immediately crosses (accumulated already 5)

    # Fire-and-immediately-clear: exactly one 1-then-0 pair, no other writes.
    assert plc.writes == [(REJECT_CMD_REG, 1), (REJECT_CMD_REG, 0)]


def test_already_passed_target_is_skipped_not_misfired(caplog):
    # Found in review: a nok verdict landing late enough that the ring has
    # already passed the reject nozzle by arm time must not fire on
    # whatever OTHER part now sits there. Skip + log ERROR once, don't
    # spam the log every tick while the part rides to exit.
    reject = FakeRejectStation(station_offset_pulses=0)
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100, reject_station=reject)

    tracker.on_part_entered(5, part_id="A")  # pulse_count_at_detection=5, slot 0
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)

    dispatcher._real_accumulated_pulses = 12  # ring already moved past target=5

    with caplog.at_level("ERROR"):
        dispatcher._arm_reject_targets(reject)
        dispatcher._arm_reject_targets(reject)  # subsequent ticks -- must not re-log
        dispatcher._arm_reject_targets(reject)

    assert 0 not in dispatcher._pending_reject_targets
    assert plc.writes == []
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1

    # A later, different occupant of the SAME physical slot index (0) must
    # still be evaluated fresh, not permanently suppressed by the stale
    # skip marker left behind for the previous occupant's detection pulse.
    tracker.free_slot(0)
    tracker.on_part_entered(105, part_id="B")  # pulse_count_at_detection=105, slot (105//10)%10=0
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)
    dispatcher._real_accumulated_pulses = 50  # well before this occupant's target=105
    dispatcher._arm_reject_targets(reject)
    assert 0 in dispatcher._pending_reject_targets
    assert dispatcher._pending_reject_targets[0] == 105


def test_disabled_reject_station_never_arms_or_fires():
    reject = FakeRejectStation(station_offset_pulses=0, enabled=False)
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100, reject_station=reject)
    plc.queue(PULSE_COUNT_REG, [0, 5, 10])
    plc.queue(PART_SENSOR_REG, [False, True, False])

    dispatcher._tick_real()
    dispatcher._tick_real()
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)
    dispatcher._tick_real()

    assert dispatcher._pending_reject_targets == {}
    assert plc.writes == []
    assert tracker.get_slot(0).assign_part_id is not None  # untouched, rides through to exit


def test_ms_to_pulses_converts_at_the_currently_measured_rate():
    dispatcher, _tracker, _plc = make_real_dispatcher()
    dispatcher._pulses_per_ms = 2.0

    assert dispatcher._ms_to_pulses(10.0) == 20  # 10ms * 2 pulses/ms
    assert dispatcher._ms_to_pulses(0.0) == 0  # 0 is a valid delay, not a sentinel -- still converts to 0 pulses
    assert dispatcher._ms_to_pulses(-5.0) == 0  # defensive -- never a negative pulse offset


def test_target_fire_pulse_applies_mid_offset_and_both_response_delays():
    # Acceptance criterion: target_fire_pulse must reflect BOTH delay
    # corrections, not just the detected pulse offset (already covered by
    # test_target_fire_pulse_reflects_actual_detected_offset_not_nominal_slot
    # with all-zero delays). _pulses_per_ms set directly rather than
    # measured via real ticks -- deterministic, and _update_pulse_rate_sample
    # itself is covered separately below.
    indexer = FakeIndexerConfig(entry_sensor_mid_offset_pulses=3)
    plc = FakeRealPlc(sim=FakeRealPlcSim(entry_sensor_response_delay_ms=4.0, reject_actuator_response_delay_ms=2.0))
    reject = FakeRejectStation(station_offset_pulses=50)
    dispatcher, tracker, _plc_client = make_real_dispatcher(reject_station=reject, indexer=indexer, plc=plc)
    dispatcher._pulses_per_ms = 1.0  # 1 pulse/ms -- 4ms -> 4 pulses, 2ms -> 2 pulses

    tracker.on_part_entered(137, part_id="A")  # slot 3, pulse_count_at_detection=137
    tracker.mark_pending(3, "s1")
    tracker.apply_station_result(3, "s1", passed=False)

    dispatcher._arm_reject_targets(reject)

    # corrected_detection = 137 - mid_offset(3) - entry_delay_pulses(4) = 130
    # target_fire_pulse = corrected_detection + station_offset(50) - actuator_delay_pulses(2) = 178
    assert dispatcher._pending_reject_targets[3] == 178


def test_pulse_rate_measured_live_from_consecutive_ticks_not_speed_scale(monkeypatch):
    # "Convert to pulses ... using ... the CURRENT RPM/speed_scale at the
    # moment of use, not a fixed conversion baked in at config-load time"
    # -- proves _pulses_per_ms comes from real elapsed wall-time between
    # ticks, not from set_speed_scale() (which only drives _tick_sim).
    import app.indexer.dispatcher as dispatcher_module

    dispatcher, _tracker, plc = make_real_dispatcher()
    plc.queue(PULSE_COUNT_REG, [0, 100])
    plc.queue(PART_SENSOR_REG, [False, False])

    times_ms = iter([1000.0, 1050.0])  # 50ms apart
    monkeypatch.setattr(dispatcher_module.time, "monotonic", lambda: next(times_ms) / 1000)

    dispatcher._tick_real()  # baseline sample, ts=1000ms, accumulated=0
    dispatcher._tick_real()  # ts=1050ms, accumulated=100 -> (100-0)/(1050-1000) = 2.0 pulses/ms

    assert dispatcher._pulses_per_ms == 2.0
    assert dispatcher._ms_to_pulses(10.0) == 20

    dispatcher.set_speed_scale(10.0)  # must not affect the measured real-mode rate at all
    assert dispatcher._pulses_per_ms == 2.0
