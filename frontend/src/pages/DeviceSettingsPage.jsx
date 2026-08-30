import { useState, useEffect } from "react";
import { Box, Typography, Button, Paper, Stack, CircularProgress, Snackbar, Alert } from "@mui/material";

import MainLayout from "../layouts/MainLayout";
import api from "../api/axios";
import { toTitleCase } from "../utils/formatLabel";

const DeviceSettingsPage = () => {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [actuators, setActuators] = useState([]);

  const [snackbar, setSnackbar] = useState({ open: false, message: "", severity: "success" });

  useEffect(() => {
    fetchActuators();
  }, []);

  const fetchActuators = async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const { data } = await api.get("/actuators");
      setActuators(data);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = async (name, state) => {
    try {
      await api.post(`/actuators/${name}/toggle`, { state });
      setActuators((prev) => prev.map((a) => (a.name === name ? { ...a, state } : a)));
      setSnackbar({
        open: true,
        message: `${toTitleCase(name)} turned ${state ? "ON" : "OFF"}`,
        severity: "success",
      });
    } catch (error) {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || `Failed to toggle ${toTitleCase(name)}`,
        severity: "error",
      });
    }
  };

  const handleCloseSnackbar = () => setSnackbar((prev) => ({ ...prev, open: false }));

  const actuatorRow = (actuator) => (
    <Paper
      key={actuator.name}
      elevation={0}
      sx={{
        p: 3,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 2,
        mb: 2,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}
    >
      <Typography fontWeight={600} fontSize="16px" sx={{ color: "black" }}>
        {toTitleCase(actuator.name)}
      </Typography>

      <Stack direction="row" spacing={2}>
        <Button
          variant={actuator.state ? "contained" : "outlined"}
          onClick={() => handleToggle(actuator.name, true)}
          sx={{
            px: 3,
            color: actuator.state ? "#fff" : "success.main",
            borderColor: "success.main",
            bgcolor: actuator.state ? "success.main" : "transparent",
            "&:hover": { bgcolor: "success.main", color: "#fff" },
          }}
        >
          ON
        </Button>

        <Button
          variant={!actuator.state ? "contained" : "outlined"}
          onClick={() => handleToggle(actuator.name, false)}
          sx={{
            px: 3,
            color: !actuator.state ? "#fff" : "error.main",
            borderColor: "error.main",
            bgcolor: !actuator.state ? "error.main" : "transparent",
            "&:hover": { bgcolor: "error.main", color: "#fff" },
          }}
        >
          OFF
        </Button>
      </Stack>
    </Paper>
  );

  return (
    <MainLayout title="Device Settings">
      {loading && (
        <Box display="flex" justifyContent="center" py={4}>
          <CircularProgress />
        </Box>
      )}

      {!loading && loadError && (
        <Typography color="error">Failed to load device settings. Check PLC connection.</Typography>
      )}

      {!loading && !loadError && actuators.length === 0 && (
        <Typography sx={{ color: "black" }}>No actuators configured.</Typography>
      )}

      {!loading && !loadError && actuators.map(actuatorRow)}

      <Snackbar
        open={snackbar.open}
        autoHideDuration={3000}
        onClose={handleCloseSnackbar}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert onClose={handleCloseSnackbar} severity={snackbar.severity} sx={{ width: "100%" }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </MainLayout>
  );
};

export default DeviceSettingsPage;
