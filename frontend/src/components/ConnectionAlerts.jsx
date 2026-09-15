import { Box, Alert } from "@mui/material";
import useConnectionHealth from "../hooks/useConnectionHealth";

// Global, red, hard-to-miss notice the instant a PLC or camera drops --
// mounted once in MainLayout so it's visible regardless of which page the
// operator is on, not just Health Check. Stacked as plain fixed-position
// Alerts rather than MUI's Snackbar (which only shows one at a time by
// default) since a PLC and a camera could both drop at once and both need
// to be seen.
const ConnectionAlerts = () => {
  const { alerts, dismiss } = useConnectionHealth();

  if (alerts.length === 0) return null;

  return (
    <Box
      sx={{
        position: "fixed",
        top: 16,
        right: 16,
        zIndex: 2000,
        display: "flex",
        flexDirection: "column",
        gap: 1,
        maxWidth: 380,
      }}
    >
      {alerts.map((alert) => (
        <Alert
          key={alert.id}
          severity="error"
          variant="filled"
          onClose={() => dismiss(alert.id)}
          sx={{ boxShadow: 4 }}
        >
          {alert.message}
        </Alert>
      ))}
    </Box>
  );
};

export default ConnectionAlerts;
