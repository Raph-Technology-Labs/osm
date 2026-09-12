import { useEffect, useState } from "react";

/**
 * Wraps the Electron main-process ZMQ->IPC bridge (window.ipc) -- live
 * camera frames + inspection results never go over REST (CLAUDE.md
 * Section 9). Returns per-camera live state keyed by camera_id, plus
 * running totals computed from the event stream itself, not re-fetched.
 */
export default function useLiveEvents(cameraIds) {
  const [frames, setFrames] = useState({}); // { camera_id: dataUrl }
  const [results, setResults] = useState({}); // { camera_id: { passed, defect_label, ... } }
  const [totals, setTotals] = useState({ total_fired: 0, total_passed: 0, total_failed: 0 });
  const [lastEvent, setLastEvent] = useState(null); // most recent raw result payload -- per-camera card use
  // Full per-slot ring snapshot, published once per dispatcher tick
  // (MessageType.RingState) -- DigitalTwin's single source of truth for
  // slot.status, replacing its old client-side reconstruction from
  // lastEvent.
  const [ringState, setRingState] = useState(null);
  // Verbose debug trail (MessageType.DispatcherLog) -- home calibration,
  // presence-sensor admits, station fires, reject arm/fire, each carrying
  // the pulse math behind it. Capped so a long-running session's log panel
  // doesn't grow unbounded; newest first for the panel to render directly.
  const MAX_DISPATCHER_LOG = 300;
  const [dispatcherLog, setDispatcherLog] = useState([]);

  useEffect(() => {
    if (!window.ipc || cameraIds.length === 0) return;

    cameraIds.forEach((id) => {
      window.ipc.handleCameraFeedMessages(id, (dataUrl) => {
        setFrames((f) => ({ ...f, [id]: dataUrl }));
      });
    });

    window.ipc.handleInspectionResultMessages((r) => {
      setResults((prev) => ({ ...prev, [r.camera_id]: r }));
      setLastEvent(r);
      setTotals((t) => ({
        total_fired: t.total_fired + 1,
        total_passed: t.total_passed + (r.passed ? 1 : 0),
        total_failed: t.total_failed + (r.passed ? 0 : 1),
      }));
    });

    window.ipc.handleRingStateMessages((state) => {
      setRingState(state);
    });

    window.ipc.handleDispatcherLogMessages((event) => {
      setDispatcherLog((prev) => [event, ...prev].slice(0, MAX_DISPATCHER_LOG));
    });
  }, [cameraIds]);

  return { frames, results, totals, setTotals, lastEvent, ringState, dispatcherLog, hasIpc: Boolean(window.ipc) };
}
