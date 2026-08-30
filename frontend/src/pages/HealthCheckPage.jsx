import { useEffect, useState } from "react";
import { Box, Chip, Typography, Paper, CircularProgress, Divider } from "@mui/material";
import { useTheme } from "@mui/material/styles";

import MainLayout from "../layouts/MainLayout";
import api from "../api/axios";
import { toTitleCase } from "../utils/formatLabel";

const statusColors = (ok, theme) =>
  ok
    ? { bgcolor: theme.palette.success.light ?? "#d9f2d9", border: theme.palette.success.main }
    : { bgcolor: "#ffe0e0", border: theme.palette.error.main };

const StatusChip = ({ ok, label }) => {
  const theme = useTheme();
  const colors = statusColors(ok, theme);
  return (
    <Chip
      label={label}
      sx={{
        bgcolor: colors.bgcolor,
        border: "1px solid",
        borderColor: colors.border,
        color: "black",
        fontWeight: "bold",
        width: 140,
      }}
    />
  );
};

const HealthCheckPage = () => {
  const [loading, setLoading] = useState(true);
  const [cameras, setCameras] = useState([]);
  const [plcHealth, setPlcHealth] = useState({ connected: false, heartbeat: null, errors: [] });

  const fetchHealth = async () => {
    try {
      const [camerasRes, plcRes] = await Promise.all([api.get("/health/cameras"), api.get("/health/plc")]);
      setCameras(camerasRes.data);
      setPlcHealth(plcRes.data);
    } catch {
      // keep last-known state on a transient poll failure
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <MainLayout title="Health Check">
      <Paper elevation={0} sx={{ p: 4, border: "1px solid", borderColor: "divider", borderRadius: 2, maxWidth: 720 }}>
        {loading ? (
          <Box display="flex" justifyContent="center" py={4}>
            <CircularProgress />
          </Box>
        ) : (
          <>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 2, color: "black" }}>
              PLC
            </Typography>
            <Box sx={{ display: "flex", flexDirection: "column", gap: 2, mb: 3 }}>
              <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <Typography sx={{ fontWeight: 600, color: "black" }}>Connection</Typography>
                <StatusChip ok={plcHealth.connected} label={plcHealth.connected ? "OK" : "OFFLINE"} />
              </Box>
              <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <Typography sx={{ fontWeight: 600, color: "black" }}>Heartbeat</Typography>
                <Typography sx={{ color: "black" }}>{plcHealth.heartbeat ?? "—"}</Typography>
              </Box>
              {plcHealth.errors.map((err) => (
                <Box key={err.name} sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <Typography sx={{ fontWeight: 600, color: "black" }}>{toTitleCase(err.name)}</Typography>
                  <StatusChip ok={err.value === 0} label={err.value === 0 ? "OK" : "TRIGGERED"} />
                </Box>
              ))}
            </Box>

            <Divider sx={{ mb: 3 }} />

            <Typography variant="h6" sx={{ fontWeight: 600, mb: 2, color: "black" }}>
              Cameras
            </Typography>
            {cameras.length === 0 && (
              <Typography sx={{ color: "black" }}>No cameras configured yet — start a session first.</Typography>
            )}
            <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {cameras.map((cam) => (
                <Box key={cam.camera_id} sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <Typography sx={{ fontWeight: 600, color: "black" }}>{toTitleCase(cam.camera_id)}</Typography>
                  <StatusChip ok={cam.connected} label={cam.connected ? "OK" : cam.initialized ? "IDLE" : "NOT INITIALIZED"} />
                </Box>
              ))}
            </Box>
          </>
        )}
      </Paper>
    </MainLayout>
  );
};

export default HealthCheckPage;
