import { useState } from "react";
import { Box, Slider, TextField, Button, Typography, Alert, useTheme } from "@mui/material";
import api from "../../api/axios";

const MIN_RPM = 0;
const MAX_RPM = 100; // PLACEHOLDER ceiling -- real max comes with real hardware, matches this
// project's convention of not inventing precise machine limits (CLAUDE.md "ask, don't invent").

const RpmControl = ({ defaultRpm = 45 }) => {
  const theme = useTheme();
  const [rpm, setRpm] = useState(defaultRpm);
  const [status, setStatus] = useState(null); // { type: 'success'|'error', text }

  const applyRpm = async (value) => {
    try {
      await api.post("/inspection/speed", { rpm: value });
      setStatus({ type: "success", text: `Speed set to ${value} RPM` });
    } catch (err) {
      setStatus({ type: "error", text: err?.response?.data?.detail || "Failed to set speed" });
    }
  };

  return (
    <Box sx={{ minWidth: 260 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
        Motor Speed
      </Typography>
      <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
        <Slider
          value={rpm}
          min={MIN_RPM}
          max={MAX_RPM}
          onChange={(_e, value) => setRpm(value)}
          onChangeCommitted={(_e, value) => applyRpm(value)}
          sx={{ flexGrow: 1, color: theme.palette.primary.main }}
        />
        <TextField
          type="number"
          size="small"
          value={rpm}
          onChange={(e) => setRpm(Number(e.target.value))}
          inputProps={{ min: MIN_RPM, max: MAX_RPM, style: { width: 56 } }}
        />
        <Button size="small" variant="contained" onClick={() => applyRpm(rpm)}>
          Apply
        </Button>
      </Box>
      {status && (
        <Alert severity={status.type} sx={{ mt: 1, py: 0 }} onClose={() => setStatus(null)}>
          {status.text}
        </Alert>
      )}
    </Box>
  );
};

export default RpmControl;
