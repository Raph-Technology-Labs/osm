"""Batches SessionResult/CameraResult inserts so the hot inspection path
never does one INSERT per part (CLAUDE.md Section 5.2's throughput design
requirement). A background thread drains a queue.Queue and flushes in
batches on a size/interval trigger -- same threading-for-hot-path
convention already used by StationDispatcher/CameraStation, not asyncio.

ring_part_id caveat: today's build fires stations on a simulation timer
(app/indexer/dispatcher.py) without ever calling
IndexerSlotTracker.on_part_entered() -- there is no real cross-station part
identity yet (that only exists once source.type: plc dispatch is wired, a
gap already flagged in dispatcher.py's own docstring). Until then,
ring_part_id here is a simple per-session, per-station incrementing
sequence number -- it uniquely identifies a station fire, but does NOT
correlate a physical part across multiple stations the way the real
IndexerSlotTracker-driven value eventually will. Don't build dashboard
queries that assume it does.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import func

from app.db.db import SessionLocal
from app.models.models import CameraResult, PartSession, SessionResult

log = logging.getLogger("results_writer")


@dataclass
class CameraResultItem:
    camera_id: str
    pipeline_name: str
    is_defective: Optional[bool]
    defect_label: Optional[str]
    defect_confidence: Optional[float]
    measurement_data: Optional[dict]
    measurement_passed: Optional[bool]
    camera_passed: Optional[bool]


@dataclass
class ResultItem:
    session_id: int
    station_id: str
    ring_part_id: int
    station_fire_no: int
    overall_passed: Optional[bool]
    rejected: Optional[bool]
    camera_results: List[CameraResultItem] = field(default_factory=list)


class ResultsWriter:
    def __init__(self, flush_interval_s: float = 2.0, flush_size: int = 20):
        self._queue: "queue.Queue[ResultItem]" = queue.Queue()
        self._flush_interval_s = flush_interval_s
        self._flush_size = flush_size
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        # Flush whatever's left synchronously so a shutdown never silently
        # drops results still sitting in the queue (CLAUDE.md Section 15:
        # "buffer must not silently drop results").
        self._flush_batch(self._drain_all())

    def enqueue(self, item: ResultItem) -> None:
        self._queue.put(item)

    def _drain_all(self) -> List[ResultItem]:
        items = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def _run(self) -> None:
        while not self._stop_event.is_set():
            batch: List[ResultItem] = []
            deadline = time.time() + self._flush_interval_s
            while len(batch) < self._flush_size:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    batch.append(self._queue.get(timeout=remaining))
                except queue.Empty:
                    break
            self._flush_batch(batch)

    def _flush_batch(self, batch: List[ResultItem]) -> None:
        if not batch:
            return
        db = SessionLocal()
        try:
            totals_by_session: Dict[int, Dict[str, int]] = {}
            for item in batch:
                sr = SessionResult(
                    session_id=item.session_id,
                    station_id=item.station_id,
                    ring_part_id=item.ring_part_id,
                    station_fire_no=item.station_fire_no,
                    overall_passed=item.overall_passed,
                    rejected=item.rejected,
                )
                db.add(sr)
                db.flush()  # populate sr.id for the CameraResult FK below
                for cam in item.camera_results:
                    db.add(
                        CameraResult(
                            session_result_id=sr.id,
                            camera_id=cam.camera_id,
                            pipeline_name=cam.pipeline_name,
                            is_defective=cam.is_defective,
                            defect_label=cam.defect_label,
                            defect_confidence=cam.defect_confidence,
                            measurement_data=cam.measurement_data,
                            measurement_passed=cam.measurement_passed,
                            camera_passed=cam.camera_passed,
                        )
                    )

                t = totals_by_session.setdefault(item.session_id, {"fired": 0, "passed": 0, "failed": 0})
                t["fired"] += 1
                if item.overall_passed:
                    t["passed"] += 1
                elif item.overall_passed is False:
                    t["failed"] += 1

            for session_id, t in totals_by_session.items():
                db.query(PartSession).filter(PartSession.id == session_id).update(
                    {
                        PartSession.total_fired: PartSession.total_fired + t["fired"],
                        PartSession.total_passed: PartSession.total_passed + t["passed"],
                        PartSession.total_failed: PartSession.total_failed + t["failed"],
                    }
                )
            db.commit()
        except Exception:
            # Never silently drop -- log loudly with the batch size so a
            # persistent failure is visible on the Health Check page's log
            # feed (CLAUDE.md Section 15), even though we don't retry here.
            db.rollback()
            log.error("batch flush failed, %d result(s) dropped", len(batch), exc_info=True)
        finally:
            db.close()


_writer: Optional[ResultsWriter] = None
_fire_counters: Dict[str, "itertools.count"] = {}
_ring_part_counters: Dict[int, "itertools.count"] = {}


def get_results_writer() -> ResultsWriter:
    global _writer
    if _writer is None:
        _writer = ResultsWriter()
    return _writer


def next_fire_no(session_id: int, station_id: str) -> int:
    """Monotonic per-(session, station) fire counter -- station_fire_no's
    real meaning ("sequential within this station's own firings")."""
    import itertools

    key = f"{session_id}:{station_id}"
    if key not in _fire_counters:
        _fire_counters[key] = itertools.count(1)
    return next(_fire_counters[key])


def next_ring_part_id(session_id: int) -> int:
    """Monotonic per-session counter, incremented on every station fire
    regardless of which station -- the ring_part_id placeholder described
    in this module's docstring. Distinct from next_fire_no (per-station) so
    a row's station_fire_no and ring_part_id aren't confusingly identical,
    but this is NOT real cross-station part correlation -- see the caveat
    above."""
    import itertools

    if session_id not in _ring_part_counters:
        _ring_part_counters[session_id] = itertools.count(1)
    return next(_ring_part_counters[session_id])
