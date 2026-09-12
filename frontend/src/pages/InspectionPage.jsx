import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Box, Typography, Button, Stack, useTheme } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import api from "../api/axios";
import useLiveEvents from "../hooks/useLiveEvents";
import DigitalTwin from "../components/inspection/DigitalTwin";
import DispatcherLogPanel from "../components/inspection/DispatcherLogPanel";
import PageTabs from "../components/inspection/PageTabs";
import StationCell from "../components/inspection/StationCell";
import RpmControl from "../components/inspection/RpmControl";

// Stations per page -- "2x2 or 3x2 ... assume 1920x1080" per the Inspection
// page spec. 4 keeps each station cell comfortably sized at that resolution;
// revisit if real screens turn out smaller/larger than assumed.
const PAGE_CAPACITY = 4;
const REVOLUTIONS_POLL_MS = 3000;

const InspectionPage = () => {
  const theme = useTheme();
  const [searchParams] = useSearchParams();
  const partCode = searchParams.get("part_code");

  const [stationOrder, setStationOrder] = useState([]); // [station_id, ...] in config order
  const [camerasByStation, setCamerasByStation] = useState({}); // { station_id: [camera_id, ...] }
  const [nSlots, setNSlots] = useState(null);
  const [stations, setStations] = useState([]); // [{station_id, name, slot_offset}]
  const [revolutions, setRevolutions] = useState(0);
  const [activePage, setActivePage] = useState(0);

  // Assume a session is already WIRED (cameras/pipeline/dispatcher created)
  // if we arrived with a part_code -- PartSelectionPage.jsx already calls
  // POST /inspection/session/start before navigating here. That call no
  // longer auto-runs the motor though, so this alone must not disable the
  // Start button -- only motorRunning does that (see below).
  const [sessionActive, setSessionActive] = useState(Boolean(partCode));
  const [motorRunning, setMotorRunning] = useState(false);
  const [sessionStatus, setSessionStatus] = useState(null); // { type, text }

  const cameraIds = useMemo(() => Object.values(camerasByStation).flat(), [camerasByStation]);
  const { frames, results, ringState, dispatcherLog, hasIpc } = useLiveEvents(cameraIds);

  const fetchConfig = () => {
    api
      .get("/inspection/config")
      .then(({ data }) => {
        const grouped = {};
        const order = [];
        (data.cameras || []).forEach(({ camera_id, station_id }) => {
          if (!grouped[station_id]) {
            grouped[station_id] = [];
            order.push(station_id);
          }
          grouped[station_id].push(camera_id);
        });
        setCamerasByStation(grouped);
        setStationOrder(order);
        setNSlots(data.n_slots || null);
        setStations(data.stations || []);
      })
      .catch(() => {});
  };

  useEffect(fetchConfig, []);

  // revolutions isn't carried on the live IPC stream (it's derived
  // server-side from total_fired/n_slots, not per-camera) -- poll it.
  useEffect(() => {
    const poll = () => {
      api
        .get("/inspection/session/current")
        .then(({ data }) => setRevolutions(data.revolutions || 0))
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, REVOLUTIONS_POLL_MS);
    return () => clearInterval(id);
  }, []);

  // One Start button: wires the session if it isn't already (skipped when
  // arriving from Part Selection, which already did this) then starts the
  // motor/ring -- no separate manual step. In today's sim-only environment
  // (no PLC attached) that's exactly right; if a real PLC is later
  // connected, gating a real motor's auto-start behind a deliberate action
  // is worth reconsidering then, but isn't a today problem.
  const handleStart = async () => {
    if (!partCode) {
      setSessionStatus({ type: "error", text: "No part selected -- start a session from Part Selection first." });
      return;
    }
    try {
      if (!sessionActive) {
        await api.post("/inspection/session/start", { part_code: partCode });
        setSessionActive(true);
        fetchConfig();
      }
      await api.post("/inspection/motor/start");
      setMotorRunning(true);
      setSessionStatus({ type: "success", text: `Running -- ${partCode}` });
    } catch (err) {
      setSessionStatus({ type: "error", text: err?.response?.data?.detail || "Failed to start" });
    }
  };

  // One Stop button: halts the motor and ends the session (finalizes the DB
  // row) together -- no separate "pause vs. end" distinction on this page.
  const handleStop = async () => {
    try {
      await api.post("/inspection/motor/stop");
      await api.post("/inspection/session/stop");
      setMotorRunning(false);
      setSessionActive(false);
      setSessionStatus({ type: "success", text: "Stopped" });
    } catch (err) {
      setSessionStatus({ type: "error", text: err?.response?.data?.detail || "Failed to stop" });
    }
  };

  const pages = useMemo(() => {
    const chunks = [];
    for (let i = 0; i < stationOrder.length; i += PAGE_CAPACITY) {
      chunks.push(stationOrder.slice(i, i + PAGE_CAPACITY));
    }
    return chunks.length ? chunks : [[]];
  }, [stationOrder]);

  const currentStations = pages[activePage] || [];

  return (
    <>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 1.5, flexShrink: 0 }}>
        Live Inspection
      </Typography>

      {/* Top control bar -- Start/Stop, RPM, totals. Fixed height, never scrolls. */}
      <Stack direction="row" spacing={3} alignItems="flex-start" flexWrap="wrap" sx={{ mb: 1.5, flexShrink: 0 }}>
        <Stack direction="row" spacing={1}>
          <Button
            variant="contained"
            color="success"
            startIcon={<PlayArrowIcon />}
            onClick={handleStart}
            disabled={motorRunning}
          >
            Start
          </Button>
          <Button
            variant="contained"
            color="error"
            startIcon={<StopIcon />}
            onClick={handleStop}
            disabled={!motorRunning}
          >
            Stop
          </Button>
        </Stack>

        <RpmControl />

        <Box sx={{ flexGrow: 1 }} />

        {/* Per-part counts (same source as the Digital Twin's OK/NOK --
            ringState.ok_total/nok_total, bumped once per part resolved at
            exit/r1) -- NOT per-camera-result counts, so this always agrees
            with the ring's green-wedge count. Per operator request
            2026-09-07, replacing the old per-camera Fired/Passed/Failed
            here (that mismatch, e.g. Passed:+2 for one part touching 2
            cameras, was the source of the earlier confusion). */}
        <Stack direction="row" spacing={3}>
          <Typography>
            Total Parts: <b>{(ringState?.ok_total || 0) + (ringState?.nok_total || 0)}</b>
          </Typography>
          <Typography sx={{ color: theme.palette.success.main }}>
            OK: <b>{ringState?.ok_total || 0}</b>
          </Typography>
          <Typography sx={{ color: theme.palette.error.main }}>
            Failed: <b>{ringState?.nok_total || 0}</b>
          </Typography>
        </Stack>
      </Stack>

      {sessionStatus && (
        <Typography
          variant="body2"
          sx={{ mb: 1, flexShrink: 0, color: sessionStatus.type === "error" ? theme.palette.error.main : theme.palette.success.main }}
        >
          {sessionStatus.text}
        </Typography>
      )}
      {!hasIpc && (
        <Typography sx={{ mb: 1, flexShrink: 0, color: theme.palette.warning.main }}>
          Live feed unavailable — this page needs the Electron app (ZMQ bridge), not a plain browser tab.
        </Typography>
      )}

      {/* Main area: camera grid (left, flexible) + digital twin (right, fixed width). No scrolling. */}
      <Box sx={{ flexGrow: 1, minHeight: 0, display: "flex", gap: 2, overflow: "hidden" }}>
        <Box sx={{ flexGrow: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <PageTabs pageCount={pages.length} activePage={activePage} onChange={setActivePage} />
          <Box
            sx={{
              flexGrow: 1,
              minHeight: 0,
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
              gap: 2,
              overflow: "hidden",
            }}
          >
            {currentStations.map((stationId) => (
              <StationCell
                key={stationId}
                stationId={stationId}
                cameras={camerasByStation[stationId] || []}
                frames={frames}
                results={results}
              />
            ))}
          </Box>
        </Box>

        <Box sx={{ width: 300, flexShrink: 0, height: "100%", display: "flex", flexDirection: "column", gap: 2 }}>
          <Box sx={{ flex: "1 1 55%", minHeight: 0 }}>
            <DigitalTwin
              nSlots={nSlots}
              stations={stations}
              ringState={ringState}
              revolutions={ringState ? ringState.revolutions : revolutions}
              running={motorRunning}
            />
          </Box>
          <Box sx={{ flex: "1 1 45%", minHeight: 0 }}>
            <DispatcherLogPanel events={dispatcherLog} />
          </Box>
        </Box>
      </Box>
    </>
  );
};

export default InspectionPage;
