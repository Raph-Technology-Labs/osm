import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Box, Typography, Button, Chip, Paper, Stack, useTheme } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import api from "../api/axios";
import useLiveEvents from "../hooks/useLiveEvents";
import useGridCapacity from "../hooks/useGridCapacity";
import DigitalTwin from "../components/inspection/DigitalTwin";
import PageTabs from "../components/inspection/PageTabs";
import StationCell from "../components/inspection/StationCell";
import SessionBreakdown, {
  SessionTotalsStrip,
  ReportActions,
} from "../components/inspection/SessionAnalysis";
import RpmControl from "../components/inspection/RpmControl";
import useSessionAnalysis from "../hooks/useSessionAnalysis";

const REVOLUTIONS_POLL_MS = 3000;

// The analysis column is a fixed rail: it never grows into the station area
// and the station area never squeezes it, so the digital twin renders at the
// same size no matter how many stations or cameras exist.
const RAIL_WIDTH = 360;

// The floor for one station: enough width for a camera tile, enough height
// for that tile plus the station's own header row. Stations shrink down to
// here and then STOP -- the overflow pages (PageTabs) instead of every tile
// getting unreadably small. Capacity is measured against these, not assumed,
// so a 4K panel fits more before paging and a laptop fewer, with no constant
// to re-tune per machine.
const MIN_STATION_W = 300;
const MIN_STATION_H = 260;

const InspectionPage = () => {
  const theme = useTheme();
  const [searchParams] = useSearchParams();
  const partCode = searchParams.get("part_code");

  const [stationOrder, setStationOrder] = useState([]); // [station_id, ...] in config order
  const [camerasByStation, setCamerasByStation] = useState({}); // { station_id: [camera_id, ...] }
  const [nSlots, setNSlots] = useState(null);
  const [stations, setStations] = useState([]); // [{station_id, name, slot_offset}]
  const [speedSetpointRpm, setSpeedSetpointRpm] = useState(45); // machine_config.yaml's plc.speed_setpoint_rpm, until fetchConfig resolves
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
  const analysis = useSessionAnalysis(sessionActive);

  // station_id -> the config row, so StationCell can show its real name and
  // offset instead of inferring them.
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
        if (data.speed_setpoint_rpm != null) setSpeedSetpointRpm(data.speed_setpoint_rpm);
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
      setSessionStatus({
        type: "error",
        text: "No part selected -- start a session from Part Selection first.",
      });
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

  // Measured, not assumed: the station area's height is whatever the flex
  // cascade left after the header, status line and totals band took theirs,
  // which is knowable only after layout -- hence ResizeObserver inside the
  // hook rather than a constant here.
  const { ref: gridRef, cols, capacity } = useGridCapacity(MIN_STATION_W, MIN_STATION_H, 12);

  const pageCount = Math.max(1, Math.ceil(stationOrder.length / capacity));

  // The window can be resized (or the config reloaded) while a later page is
  // showing -- capacity grows and that page stops existing. Clamp back to the
  // first rather than render an empty area.
  useEffect(() => {
    if (activePage > pageCount - 1) setActivePage(0);
  }, [pageCount, activePage]);

  const currentStations = stationOrder.slice(
    activePage * capacity,
    activePage * capacity + capacity
  );

  return (
    // Two columns from the very top: the header belongs to the LEFT column
    // only, so the analysis rail starts level with it. overflow: hidden on the
    // root means neither column can push the page sideways.
    <Box sx={{ height: "100%", minHeight: 0, display: "flex", gap: 2, overflow: "hidden" }}>
      {/* ── LEFT: header, totals band, station tabs, stations ────────── */}
      <Box
        sx={{
          flex: "1 1 0",
          minWidth: 0, // without this the column refuses to shrink and clips
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          overflow: "hidden",
        }}
      >
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
            gap: 2,
            flexWrap: "wrap",
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: "wrap" }}>
              <Typography sx={{ fontWeight: 800, fontSize: "2.4rem", letterSpacing: "0.02em",
                  lineHeight: 1.05, }}>
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

          {/* Speed setpoint. Start/Stop sits at the far end of the same bar. */}
          <RpmControl defaultRpm={speedSetpointRpm} />

          <Box sx={{ flexGrow: 1 }} />

          <Stack direction="row" spacing={2} alignItems="center">
            <Button
              variant="contained"
              color="success"
              size="large"
              startIcon={<PlayArrowIcon />}
              onClick={handleStart}
              disabled={motorRunning}
              sx={{
                px: 4.5,
                py: 1.5,
                fontSize: "1.1rem",
                fontWeight: 800,
                letterSpacing: 0.5,
                minWidth: 160,
                borderRadius: 2,
                boxShadow: 3,
                textTransform: "none",
                "& .MuiSvgIcon-root": { fontSize: 26 },
                "& .MuiButton-startIcon": { mr: 1.25 },
              }}
            >
              Start
            </Button>

            <Button
              variant="contained"
              color="error"
              size="large"
              startIcon={<StopIcon />}
              onClick={handleStop}
              disabled={!motorRunning}
              sx={{
                px: 4.5,
                py: 1.5,
                fontSize: "1.1rem",
                fontWeight: 800,
                letterSpacing: 0.5,
                minWidth: 160,
                borderRadius: 2,
                boxShadow: 3,
                textTransform: "none",
                "& .MuiSvgIcon-root": { fontSize: 26 },
                "& .MuiButton-startIcon": { mr: 1.25 },
              }}
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
                Live feed unavailable — this page needs the Electron app (ZMQ bridge), not a plain
                browser tab.
              </Typography>
            )}
          </Box>
        )}

        {/* Headline counts across the full station width: this is the one
            number an operator reads from across the room, and the 360px rail
            could never make it big enough. flexShrink: 0 means the station
            area below gives up the height instead, and these digits never
            degrade no matter how dense the station grid gets. */}
        <SessionTotalsStrip ringState={ringState} />

        {/* Renders itself away at a single page -- a tab strip that never
            changes anything is a control that lies about having options. */}
        <PageTabs pageCount={pageCount} activePage={activePage} onChange={setActivePage} />

        {/* Stations divide this space and never scroll: these are live values,
            and a value an operator has to scroll to find is a value they will
            miss. They shrink only down to MIN_STATION_*; past that the extras
            move to the next tab rather than every tile becoming a thumbnail.
            gridRef is what the capacity above was measured from. */}
        <Box
          ref={gridRef}
          sx={{
            flexGrow: 1,
            minHeight: 0,
            overflow: "hidden",
            display: "grid",
            gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
            gridAutoRows: "1fr",
            alignItems: "start",
            gap: 1.5,
          }}
        >
          {currentStations.map((stationId) => (
            <StationCell
              key={stationId}
              stationId={stationId}
              index={stationOrder.indexOf(stationId)}
              station={stationById[stationId]}
              cameras={camerasByStation[stationId] || []}
              frames={frames}
              results={results}
              stationTotals={analysis?.stations?.[stationId]}
            />
          ))}
        </Box>
      </Box>

      {/* ── RIGHT: fixed rail, report actions → twin → breakdown ─────── */}
      <Box
        sx={{
          flex: `0 0 ${RAIL_WIDTH}px`, // never grows into the stations, never shrinks
          minWidth: 0,
          height: "100%",
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 2,
          pr: 0.5,
        }}
      >
        <ReportActions />

        {/* DigitalTwin's own Paper sets height:100%, which collapses to a
            sliver inside a scrolling column — override it so the ring renders
            at its natural size and nothing is clipped. */}
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

        <SessionBreakdown analysis={analysis} />
      </Box>
    </Box>
  );
};

export default InspectionPage;