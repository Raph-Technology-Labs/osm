import { useEffect, useState } from "react";
import { Box, Card, Chip, Grid, Typography, useTheme } from "@mui/material";
import api from "../api/axios";

const InspectionPage = () => {
  const theme = useTheme();
  const [cameraIds, setCameraIds] = useState([]);
  const [frames, setFrames] = useState({}); // { camera_id: dataUrl }
  const [results, setResults] = useState({}); // { camera_id: { passed, defect_label } }
  const [totals, setTotals] = useState({ total_fired: 0, total_passed: 0, total_failed: 0 });

  useEffect(() => {
    api.get("/inspection/config").then(({ data }) => {
      setCameraIds(data.cameras.map((c) => c.camera_id));
    }).catch(() => {});
    api.get("/inspection/session/current").then(({ data }) => setTotals(data)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!window.ipc || cameraIds.length === 0) return;
    cameraIds.forEach((id) => {
      window.ipc.handleCameraFeedMessages(id, (dataUrl) => {
        setFrames((f) => ({ ...f, [id]: dataUrl }));
      });
    });
    window.ipc.handleInspectionResultMessages((r) => {
      setResults((prev) => ({ ...prev, [r.camera_id]: r }));
      setTotals((t) => ({
        total_fired: t.total_fired + 1,
        total_passed: t.total_passed + (r.passed ? 1 : 0),
        total_failed: t.total_failed + (r.passed ? 0 : 1),
      }));
    });
  }, [cameraIds]);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ fontWeight: 600, mb: 2 }}>
        Live Inspection
      </Typography>

      {!window.ipc && (
        <Typography sx={{ mb: 2, color: theme.palette.warning.main }}>
          Live feed unavailable — this page needs the Electron app (ZMQ bridge), not a plain browser tab.
        </Typography>
      )}

      <Grid container spacing={2}>
        {cameraIds.map((id) => {
          const result = results[id];
          return (
            <Grid item xs={12} md={6} key={id}>
              <Card sx={{ p: 1.5, borderRadius: "8px" }}>
                <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
                  <Typography sx={{ fontWeight: 600 }}>{id}</Typography>
                  <Chip
                    label={result ? (result.passed ? "OK" : `NOK${result.defect_label ? ` · ${result.defect_label}` : ""}`) : "—"}
                    color={result ? (result.passed ? "success" : "error") : "default"}
                    size="small"
                  />
                </Box>
                <Box
                  sx={{
                    width: "100%",
                    aspectRatio: "4 / 3",
                    bgcolor: theme.palette.grey[900],
                    borderRadius: "6px",
                    overflow: "hidden",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {frames[id] ? (
                    <img src={frames[id]} alt={id} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
                  ) : (
                    <Typography sx={{ color: theme.palette.grey[500] }}>Waiting for frames…</Typography>
                  )}
                </Box>
              </Card>
            </Grid>
          );
        })}
      </Grid>

      <Box sx={{ mt: 3, display: "flex", gap: 3 }}>
        <Typography>Fired: <b>{totals.total_fired}</b></Typography>
        <Typography sx={{ color: theme.palette.success.main }}>Passed: <b>{totals.total_passed}</b></Typography>
        <Typography sx={{ color: theme.palette.error.main }}>Failed: <b>{totals.total_failed}</b></Typography>
      </Box>
    </Box>
  );
};

export default InspectionPage;
