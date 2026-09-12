import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Box, Typography, Button, Chip, Paper, Stack, useTheme } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import api from "../api/axios";
import useLiveEvents from "../hooks/useLiveEvents";
import useResultTally from "../hooks/useResultTally";
import DigitalTwin from "../components/inspection/DigitalTwin";
import PageTabs from "../components/inspection/PageTabs";
import StationCell from "../components/inspection/StationCell";
import SessionBreakdown, { SessionTotals } from "../components/inspection/SessionAnalysis";
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
  const { frames, results, ringState, hasIpc } = useLiveEvents(cameraIds);
  const tally = useResultTally(results);

  // station_id -> the config row, so StationCell can show its real name,
  // offset and pipeline instead of inferring them.
  const stationById = useMemo(() => {
    const map = {};
    stations.forEach((s) => {
      map[s.station_id] = s;
    });
    return map;
  }, [stations]);

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
    // Two columns from the very top of the page: the header belongs to the
    // LEFT column only, so the analysis column starts level with it and the
    // top-right space is used rather than left blank.
    <Box sx={{ height: "100%", minHeight: 0, display: "flex", gap: 2 }}>
      {/* ── LEFT: header, then the station list (the only thing that scrolls) ── */}
      <Box sx={{ flexGrow: 1, minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0 }}>
        <Paper
          variant="outlined"
          sx={{
            borderRadius: 2,
            px: 2,
            py: 1.5,
            mb: 1.5,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            gap: 2.5,
            flexWrap: "wrap",
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: "wrap" }}>
              <Typography sx={{ fontWeight: 700, fontSize: "1.05rem" }}>
                {partCode || "No part selected"}
              </Typography>
              <Chip
                size="small"
                label={motorRunning ? "RUNNING" : "STOPPED"}
                sx={{
                  height: 22,
                  fontWeight: 700,
                  fontSize: "0.65rem",
                  bgcolor: motorRunning ? "success.light" : "action.hover",
                  color: motorRunning ? "success.dark" : "text.secondary",
                }}
              />
              <Chip
                size="small"
                label={hasIpc ? "Live feed linked" : "No live feed"}
                sx={{
                  height: 22,
                  fontWeight: 600,
                  fontSize: "0.65rem",
                  bgcolor: hasIpc ? "info.light" : "warning.light",
                  color: hasIpc ? "info.dark" : "warning.dark",
                }}
              />
            </Stack>
            <Typography variant="caption" sx={{ color: "text.secondary" }}>
              {nSlots ? `Ring ${nSlots} slots` : "Ring —"} · {stations.length} stations
            </Typography>
          </Box>

          {/* Speed and run control sit together: Apply writes the setpoint,
              Start/Stop act on the same motor. Separating them put two halves
              of one decision at opposite ends of the bar. */}
          <RpmControl />

          <Stack direction="row" spacing={1} alignItems="center">
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
        </Paper>

        {(sessionStatus || !hasIpc) && (
          <Box sx={{ mb: 1.5, flexShrink: 0 }}>
            {sessionStatus && (
              <Typography
                variant="body2"
                sx={{
                  color:
                    sessionStatus.type === "error"
                      ? theme.palette.error.main
                      : theme.palette.success.main,
                }}
              >
                {sessionStatus.text}
              </Typography>
            )}
            {!hasIpc && (
              <Typography variant="body2" sx={{ color: theme.palette.warning.main }}>
                Live feed unavailable — this page needs the Electron app (ZMQ bridge), not a plain browser tab.
              </Typography>
            )}
          </Box>
        )}

        <PageTabs pageCount={pages.length} activePage={activePage} onChange={setActivePage} />

        <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: "auto", pr: 1 }}>
          {currentStations.map((stationId) => (
            <StationCell
              key={stationId}
              stationId={stationId}
              station={stationById[stationId]}
              cameras={camerasByStation[stationId] || []}
              frames={frames}
              results={results}
              tally={tally}
            />
          ))}
        </Box>
      </Box>

      {/* ── RIGHT: totals → twin → breakdown, starting at the top of the page ── */}
      <Box
        sx={{
          width: 360,
          flexShrink: 0,
          height: "100%",
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 2,
          pr: 0.5,
        }}
      >
        <SessionTotals ringState={ringState} />

        {/* DigitalTwin's own Paper sets height:100%, which collapsed to a
            sliver once this column started scrolling — override it here so
            the ring renders at its natural size and nothing is clipped. */}
        <Box
          sx={{
            flexShrink: 0,
            "& > .MuiPaper-root": { height: "auto", overflow: "visible" },
          }}
        >
          <DigitalTwin
            nSlots={nSlots}
            stations={stations}
            ringState={ringState}
            revolutions={ringState ? ringState.revolutions : revolutions}
            running={motorRunning}
          />
        </Box>

        <SessionBreakdown tally={tally} />
      </Box>
    </Box>
  );
};

export default InspectionPage;