import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Box, Typography, Button, Stack, useTheme } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import api from "../api/axios";
import MainLayout from "../layouts/MainLayout";
import useLiveEvents from "../hooks/useLiveEvents";
import DigitalTwin from "../components/inspection/DigitalTwin";
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

  // Assume a session is already running if we arrived with a part_code --
  // PartSelectionPage.jsx already calls POST /inspection/session/start
  // before navigating here. Start/Stop below just let you restart/stop it
  // without leaving this page.
  const [running, setRunning] = useState(Boolean(partCode));
  const [sessionStatus, setSessionStatus] = useState(null); // { type, text }

  const cameraIds = useMemo(() => Object.values(camerasByStation).flat(), [camerasByStation]);
  const { frames, results, totals, lastEvent, hasIpc } = useLiveEvents(cameraIds);

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

  const handleStart = async () => {
    if (!partCode) {
      setSessionStatus({ type: "error", text: "No part selected -- start a session from Part Selection first." });
      return;
    }
    try {
      await api.post("/inspection/session/start", { part_code: partCode });
      setRunning(true);
      setSessionStatus({ type: "success", text: `Session started for ${partCode}` });
      fetchConfig();
    } catch (err) {
      setSessionStatus({ type: "error", text: err?.response?.data?.detail || "Failed to start session" });
    }
  };

  const handleStop = async () => {
    try {
      await api.post("/inspection/session/stop");
      setRunning(false);
      setSessionStatus({ type: "success", text: "Session stopped" });
    } catch (err) {
      setSessionStatus({ type: "error", text: err?.response?.data?.detail || "Failed to stop session" });
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
    <MainLayout title="Live Inspection" noScroll>
      {/* Top control bar -- Start/Stop, RPM, totals. Fixed height, never scrolls. */}
      <Stack direction="row" spacing={3} alignItems="flex-start" flexWrap="wrap" sx={{ mb: 1.5, flexShrink: 0 }}>
        <Stack direction="row" spacing={1}>
          <Button
            variant="contained"
            color="success"
            startIcon={<PlayArrowIcon />}
            onClick={handleStart}
            disabled={running}
          >
            Start
          </Button>
          <Button variant="contained" color="error" startIcon={<StopIcon />} onClick={handleStop} disabled={!running}>
            Stop
          </Button>
        </Stack>

        <RpmControl />

        <Box sx={{ flexGrow: 1 }} />

        <Stack direction="row" spacing={3}>
          <Typography>
            Fired: <b>{totals.total_fired}</b>
          </Typography>
          <Typography sx={{ color: theme.palette.success.main }}>
            Passed: <b>{totals.total_passed}</b>
          </Typography>
          <Typography sx={{ color: theme.palette.error.main }}>
            Failed: <b>{totals.total_failed}</b>
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

        <Box sx={{ width: 300, flexShrink: 0, height: "100%" }}>
          <DigitalTwin nSlots={nSlots} stations={stations} lastEvent={lastEvent} revolutions={revolutions} running={running} />
        </Box>
      </Box>
    </MainLayout>
  );
};

export default InspectionPage;
