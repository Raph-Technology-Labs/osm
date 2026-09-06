import { useEffect, useMemo, useRef, useState } from "react";
import { Box, Typography, useTheme } from "@mui/material";
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
  const [stationOrder, setStationOrder] = useState([]); // [station_id, ...] in config order
  const [camerasByStation, setCamerasByStation] = useState({}); // { station_id: [camera_id, ...] }
  const [nSlots, setNSlots] = useState(null);
  const [stations, setStations] = useState([]); // [{station_id, name, slot_offset}]
  const [revolutions, setRevolutions] = useState(0);
  const [activePage, setActivePage] = useState(0);
  const trailRef = useRef([]);
  const [trail, setTrail] = useState([]);

  const cameraIds = useMemo(
    () => Object.values(camerasByStation).flat(),
    [camerasByStation]
  );
  const { frames, results, totals, lastEvent, hasIpc } = useLiveEvents(cameraIds);

  // Initial config: cameras grouped by station, real station ring positions.
  useEffect(() => {
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
  }, []);

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

  // Feed the digital twin's trail from each new live result -- see
  // DigitalTwin.jsx's caption for why this is a proxy, not real slot state.
  useEffect(() => {
    if (!lastEvent || !nSlots) return;
    const entry = {
      key: `${lastEvent.camera_id}-${totals.total_fired}`,
      slot: totals.total_fired % nSlots,
      state: lastEvent.passed ? "ok" : "nok",
    };
    trailRef.current = [...trailRef.current, entry].slice(-8);
    setTrail(trailRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);

  const pages = useMemo(() => {
    const chunks = [];
    for (let i = 0; i < stationOrder.length; i += PAGE_CAPACITY) {
      chunks.push(stationOrder.slice(i, i + PAGE_CAPACITY));
    }
    return chunks.length ? chunks : [[]];
  }, [stationOrder]);

  const currentStations = pages[activePage] || [];

  return (
    <MainLayout title="Live Inspection">
      {!hasIpc && (
        <Typography sx={{ mb: 2, color: theme.palette.warning.main }}>
          Live feed unavailable — this page needs the Electron app (ZMQ bridge), not a plain browser tab.
        </Typography>
      )}

      <DigitalTwin nSlots={nSlots} stations={stations} recentEvents={trail} revolutions={revolutions} />

      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 2, mb: 1 }}>
        <PageTabs pageCount={pages.length} activePage={activePage} onChange={setActivePage} />
        <RpmControl />
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 2,
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

      <Box sx={{ mt: 3, display: "flex", gap: 3 }}>
        <Typography>
          This page — Fired: <b>{totals.total_fired}</b>
        </Typography>
        <Typography sx={{ color: theme.palette.success.main }}>
          Passed: <b>{totals.total_passed}</b>
        </Typography>
        <Typography sx={{ color: theme.palette.error.main }}>
          Failed: <b>{totals.total_failed}</b>
        </Typography>
      </Box>
    </MainLayout>
  );
};

export default InspectionPage;
