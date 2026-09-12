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
    watches: Optional[List[str]] = None  # spec11 Part 2 -- None means "watch every inspection station"
    actuator_reg: Optional[int] = None  # spec14 followup #2 -- None means "use the shared reject_cmd register"


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

    def reject_stations(self):
        # Real ResolvedMachineConfig.reject_stations() sorts by
        # station_offset_pulses (ring order) -- mirrored here since
        # _tick_real's overlapping-watches safety depends on that order,
        # not on YAML/list declaration order.
        return sorted(
            (s for s in self.stations if s.type == "reject"),
            key=lambda s: s.station_offset_pulses,
        )


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
    reject_stations: Optional[List[FakeRejectStation]] = None,
    inspection_ids=("s1",),
    indexer: Optional[FakeIndexerConfig] = None,
    plc: Optional[FakeRealPlc] = None,
):
    # reject_stations (plural, spec11 Part 2) takes precedence; reject_station
    # (singular) stays as sugar for the common single-reject-station case so
    # every pre-Part-2 test call site here needs no change.
    if reject_stations is not None:
        rejects = list(reject_stations)
    elif reject_station is not None:
        rejects = [reject_station]
    else:
        rejects = []

    stations = [FakeInspectionStation(id=sid) for sid in inspection_ids] + rejects
    config = FakeRealResolvedConfig(stations, indexer=indexer, plc=plc)
    offsets = {sid: 0 for sid in inspection_ids}
    offsets.update({r.id: 0 for r in rejects})
    tracker = IndexerSlotTracker(
        n_slots=n_slots,
        encoder_cpr=encoder_cpr,
        station_pulse_offsets=offsets,
        inspection_station_ids=list(inspection_ids),
    )
    registry = FakeStationRegistry()
    plc_client = FakePlcClient()
    dispatcher = StationDispatcher(config, registry, tracker, plc_client=plc_client)
    # Drive _tick_real() directly and deterministically -- no real timer.
    dispatcher._stopped = False
    dispatcher._schedule_tick = lambda: None
    return dispatcher, tracker, plc_client


def test_first_rising_edge_calibrates_home_and_derives_slot_index():
    # An incremental encoder has no absolute reference of its own -- raw
    # pulse=0 is just wherever it was at power-on, not tied to any
    # physical location. So the FIRST part_sensor rising edge each
    # session calibrates home_offset_pulses (see StationDispatcher
    # .home_offset_pulses), and that same edge's own detection is
    # necessarily home-relative pulse 0 -- it defines the zero, it can't
    # be offset from it.
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100)
    plc.queue(PULSE_COUNT_REG, [55, 63])
    plc.queue(PART_SENSOR_REG, [False, True])

    dispatcher._tick_real()  # baseline reading, no edge
    dispatcher._tick_real()  # rising edge: accumulated = 63-55 = 8, calibrates home

    assert dispatcher.home_offset_pulses == 8
    slot_index = 0  # home-relative pulse 0 at calibration -- always slot 0
    record = tracker.get_slot(slot_index)
    assert record.assign_part_id is not None
    assert record.pulse_count_at_detection == 0


def test_second_rising_edge_is_home_relative_not_raw():
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100)
    # ticks: baseline(55) -> edge(63, calibrates home=8) -> no edge(70) ->
    # edge(75) -- second part detected 12 raw pulses after calibration.
    plc.queue(PULSE_COUNT_REG, [55, 63, 70, 75])
    plc.queue(PART_SENSOR_REG, [False, True, False, True])

    dispatcher._tick_real()
    dispatcher._tick_real()  # calibrates home_offset_pulses = 8
    dispatcher._tick_real()
    dispatcher._tick_real()  # second edge: accumulated = 75-55 = 20, home-relative = 20-8 = 12

    assert dispatcher.home_offset_pulses == 8
    slot_index = (12 // tracker.pulses_per_slot) % tracker.n_slots
    record = tracker.get_slot(slot_index)
    assert record.assign_part_id is not None
    assert record.pulse_count_at_detection == 12


def test_already_high_on_first_poll_is_baseline_not_a_phantom_edge():
    # Found via h/w integration testing 2026-09-11: with no part physically
    # present, part_sensor happened to already read HIGH on the very first
    # poll (stuck bit / idle-high default / wiring quirk). There's no
    # genuine prior reading on tick 1 to compare against, so this must be
    # treated as establishing a baseline, never as a rising edge -- doing
    # otherwise silently admits a phantom part AND miscalibrates home off a
    # bogus reading. Sensor staying High across further ticks (no real
    # transition ever happens) must never admit anything either.
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100)
    plc.queue(PULSE_COUNT_REG, [10, 20, 30])
    plc.queue(PART_SENSOR_REG, [True, True, True])

    dispatcher._tick_real()  # first-ever poll: True -- baseline only, no edge
    dispatcher._tick_real()  # still True: no transition, no edge
    dispatcher._tick_real()  # still True: no transition, no edge

    assert tracker.in_flight_count == 0
    assert dispatcher.home_offset_pulses is None


def test_level_high_across_ticks_counts_once_not_per_tick():
    # A genuine False -> True transition (real edge, after baseline is
    # already established) admits exactly one part; the sensor staying
    # True on subsequent polls must not re-trigger -- one part in, not
    # three.
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100)
    plc.queue(PULSE_COUNT_REG, [10, 10, 20, 30])
    plc.queue(PART_SENSOR_REG, [False, True, True, True])

    dispatcher._tick_real()  # baseline: False
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
    assert tracker.reject_removed == 1


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


def test_actuator_reg_unset_uses_the_shared_reject_cmd_register():
    # spec14 followup #2 groundwork -- omitting actuator_reg (every
    # existing part config does) must preserve today's shared-register
    # behavior exactly, unchanged.
    reject = FakeRejectStation(station_offset_pulses=0)  # actuator_reg left at its None default
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100, reject_station=reject)
    plc.queue(PULSE_COUNT_REG, [0, 5])
    plc.queue(PART_SENSOR_REG, [False, True])

    dispatcher._tick_real()
    dispatcher._tick_real()
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)

    plc.queue(PULSE_COUNT_REG, [5])
    plc.queue(PART_SENSOR_REG, [False])
    dispatcher._tick_real()

    assert plc.writes == [(REJECT_CMD_REG, 1), (REJECT_CMD_REG, 0)]


def test_actuator_reg_set_routes_firing_to_that_specific_register():
    # A reject station with its own actuator_reg must fire THAT register,
    # not the shared reject_cmd -- the one-line config change that makes
    # wiring in a second physical actuator possible later.
    dedicated_reg = 50123
    reject = FakeRejectStation(station_offset_pulses=0, actuator_reg=dedicated_reg)
    dispatcher, tracker, plc = make_real_dispatcher(n_slots=10, encoder_cpr=100, reject_station=reject)
    plc.queue(PULSE_COUNT_REG, [0, 5])
    plc.queue(PART_SENSOR_REG, [False, True])

    dispatcher._tick_real()
    dispatcher._tick_real()
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)

    plc.queue(PULSE_COUNT_REG, [5])
    plc.queue(PART_SENSOR_REG, [False])
    dispatcher._tick_real()

    assert plc.writes == [(dedicated_reg, 1), (dedicated_reg, 0)]
    assert (REJECT_CMD_REG, 1) not in plc.writes  # never touches the shared register
    assert tracker.get_slot(0).assign_part_id is None  # still fires/transitions correctly
    assert tracker.reject_removed == 1


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


# --- spec11 Part 2 (dual reject routing): overlapping-watches safety ---
#
# Today's actual configs never give two reject stations overlapping
# watches: lists, but nothing in the schema forbids it, and _arm_reject_
# targets' cross-reject-station guards only matter AT ALL when it happens.
# These tests construct that overlap directly so the mechanism itself is
# proven safe, not just "safe because today's specific layout happens not
# to exercise it."

def test_overlapping_watches_does_not_overwrite_the_pending_target():
    r1 = FakeRejectStation(id="r1", station_offset_pulses=30, watches=["s1"])
    r2 = FakeRejectStation(id="r2", station_offset_pulses=80, watches=["s1"])  # overlaps r1 on s1
    dispatcher, tracker, _plc = make_real_dispatcher(reject_stations=[r1, r2])

    tracker.on_part_entered(5, part_id="A")  # slot 0, pulse_count_at_detection=5
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)

    dispatcher._arm_reject_targets(r1)
    dispatcher._arm_reject_targets(r2)  # must NOT overwrite r1's claim with 5+80=85

    assert dispatcher._pending_reject_targets[0] == 5 + 30  # r1's target, unmodified
    assert dispatcher._pending_reject_armed_by[0] is r1


def test_overlapping_watches_physically_first_station_wins_regardless_of_declared_order():
    r1 = FakeRejectStation(id="r1", station_offset_pulses=30, watches=["s1"])
    r2 = FakeRejectStation(id="r2", station_offset_pulses=80, watches=["s1"])
    # Declared r2-before-r1 -- reject_stations() must still process them in
    # ring order (by station_offset_pulses), not declaration order.
    dispatcher, tracker, _plc = make_real_dispatcher(reject_stations=[r2, r1])

    tracker.on_part_entered(5, part_id="A")
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)

    for rs in dispatcher.resolved_config.reject_stations():
        dispatcher._arm_reject_targets(rs)

    assert dispatcher._pending_reject_targets[0] == 5 + 30  # r1 (physically first), never r2
    assert dispatcher._pending_reject_armed_by[0] is r1


def test_overlapping_watches_fires_using_the_armer_not_whichever_station_is_checked_last(monkeypatch):
    # The dangerous version of this bug: if firing used whichever reject
    # station's loop iteration happened to notice the crossing (instead of
    # whichever one actually armed it), and that station's .watches
    # didn't happen to match, transition_reject() would silently no-op
    # even though the physical reject_cmd register was already written --
    # a part physically discarded but the tracker still believes it's
    # in-flight.
    r1 = FakeRejectStation(id="r1", station_offset_pulses=0, watches=["s1"])
    r2 = FakeRejectStation(id="r2", station_offset_pulses=50, watches=["s1"])
    dispatcher, tracker, plc = make_real_dispatcher(reject_stations=[r2, r1])  # declared out of ring order
    plc.queue(PULSE_COUNT_REG, [0, 5])
    plc.queue(PART_SENSOR_REG, [False, True])

    dispatcher._tick_real()
    dispatcher._tick_real()  # part enters at accumulated=5, slot 0
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)  # nok -- both r1 and r2 watch s1

    calls = []
    real_transition_reject = tracker.transition_reject

    def spy(slot_id, reject_station):
        calls.append(reject_station.id)
        return real_transition_reject(slot_id, reject_station)

    tracker.transition_reject = spy

    plc.queue(PULSE_COUNT_REG, [5])  # flat -- r1's target (0+5=5) == accumulated(5): arms AND fires this tick
    plc.queue(PART_SENSOR_REG, [False])
    dispatcher._tick_real()

    assert calls == ["r1"]  # never r2, even though r2 also watches s1
    assert tracker.get_slot(0).assign_part_id is None
    assert tracker.reject_removed == 1


def test_overlapping_watches_one_stations_missed_window_does_not_block_a_laters_chance():
    # r1 (physically first) misses its window (nok verdict arrived too
    # late) -- r2 (physically later, also watching s1) must still get its
    # own independent chance to arm the SAME occupant, not be silently
    # skipped just because r1 already logged a miss for it.
    r1 = FakeRejectStation(id="r1", station_offset_pulses=5, watches=["s1"])
    r2 = FakeRejectStation(id="r2", station_offset_pulses=50, watches=["s1"])
    dispatcher, tracker, _plc = make_real_dispatcher(reject_stations=[r1, r2])

    tracker.on_part_entered(5, part_id="A")  # pulse_count_at_detection=5
    tracker.mark_pending(0, "s1")
    tracker.apply_station_result(0, "s1", passed=False)

    dispatcher._real_accumulated_pulses = 12  # already past r1's target (5+5=10)
    dispatcher._arm_reject_targets(r1)  # skips + logs, does NOT arm
    assert 0 not in dispatcher._pending_reject_targets

    dispatcher._arm_reject_targets(r2)  # r2's target (5+50=55) is still ahead -- gets its own chance
    assert dispatcher._pending_reject_targets[0] == 55
    assert dispatcher._pending_reject_armed_by[0] is r2


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
