import { useCallback, useEffect, useRef, useState } from "react";
import api from "../api/axios";

// Polls the same endpoints the Health Check page uses (/health/plc,
// /health/cameras) so a PLC or camera disconnect is surfaced globally, not
// only to whoever happens to have that page open. REST polling, not a live
// push -- these are low-frequency status checks (CLAUDE.md Section 9
// reserves the ZMQ/IPC path for the high-rate camera-feed/inspection-result
// stream only), so a few seconds of latency to notice a disconnect is fine.
const POLL_MS = 4000;
const ALERT_AUTO_DISMISS_MS = 10000;

export default function useConnectionHealth() {
  const [alerts, setAlerts] = useState([]); // [{id, message}]
  // null (not false) on each ref -- the FIRST poll only establishes a
  // baseline, it never fires an alert, matching how this codebase already
  // treats "no genuine prior reading yet" elsewhere (e.g. the part_sensor
  // first-poll baseline in dispatcher.py) -- otherwise a PLC/camera that's
  // already down when the app loads would immediately alert on load rather
  // than only on an actual transition while someone's watching.
  const prevPlcConnected = useRef(null);
  const prevCameraConnected = useRef({}); // camera_id -> bool | undefined

  // Stable identity (useCallback, empty deps -- both only ever use the
  // setAlerts updater form) so the polling effect below can depend on them
  // without re-running/re-subscribing every render.
  const dismiss = useCallback((id) => setAlerts((prev) => prev.filter((a) => a.id !== id)), []);

  const pushAlert = useCallback((message) => {
    const id = `${Date.now()}-${Math.random()}`;
    setAlerts((prev) => [...prev, { id, message }]);
    setTimeout(() => dismiss(id), ALERT_AUTO_DISMISS_MS);
  }, [dismiss]);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const [{ data: plc }, { data: cameras }] = await Promise.all([
          api.get("/health/plc"),
          api.get("/health/cameras"),
        ]);
        if (cancelled) return;

        if (prevPlcConnected.current === true && plc.connected === false) {
          pushAlert("PLC disconnected");
        }
        prevPlcConnected.current = plc.connected;

        cameras.forEach((cam) => {
          const prevConnected = prevCameraConnected.current[cam.camera_id];
          if (prevConnected === true && cam.connected === false) {
            pushAlert(`Camera ${cam.camera_id} (station ${cam.station_id}) disconnected`);
          }
          prevCameraConnected.current[cam.camera_id] = cam.connected;
        });
      } catch {
        // Health endpoints themselves unreachable (backend down, no
        // session token yet) -- not itself a PLC/camera disconnect worth
        // alerting on here; just try again next interval.
      }
    };

    poll();
    const intervalId = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [pushAlert]);

  return { alerts, dismiss };
}
