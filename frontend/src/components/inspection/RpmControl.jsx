import { useState } from "react";
import { Box, Slider, TextField, Button, Typography, Alert, useTheme } from "@mui/material";
import api from "../../api/axios";

const MIN_RPM = 0;
const MAX_RPM = 100; // PLACEHOLDER ceiling -- real max comes with real hardware, matches this
// project's convention of not inventing precise machine limits (CLAUDE.md "ask, don't invent").

// Browsers hide the number input's spinner arrows until the pointer is over
// the field (Chrome sets opacity:0 on the inner spin button, Firefox hides it
// entirely unless -moz-appearance says otherwise). On a machine screen the
// operator needs to SEE that the value is nudgeable before reaching for it,
// so both are forced visible.
const spinnerAlwaysVisible = {
  "& input[type=number]": {
    MozAppearance: "number-input",
  },
  "& input[type=number]::-webkit-outer-spin-button, & input[type=number]::-webkit-inner-spin-button":
    {
      WebkitAppearance: "inner-spin-button",
      opacity: 1,
      margin: 0,
      height: 30,
      cursor: "pointer",
    },
};

const RpmControl = ({ defaultRpm = 45 }) => {
  const theme = useTheme();
  const [appliedRpm, setAppliedRpm] = useState(defaultRpm); // last value actually written to the PLC
  const [rpm, setRpm] = useState(defaultRpm); // live value while dragging/typing, before Apply
  const [status, setStatus] = useState(null); // { type: 'success'|'error', text }

  const applyRpm = async (value) => {
    try {
      await api.post("/inspection/speed", { rpm: value });
      setAppliedRpm(value);
      setStatus({ type: "success", text: `Speed set to ${value} RPM` });
    } catch (err) {
      setStatus({ type: "error", text: err?.response?.data?.detail || "Failed to set speed" });
    }
  };

  return (
    <Box sx={{ minWidth: 260 }}>
      <Box sx={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", mb: 1 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          Motor Speed
        </Typography>
        <Typography variant="body2" sx={{ color: theme.palette.text.secondary }}>
          Current: <b style={{ color: theme.palette.text.primary }}>{appliedRpm} RPM</b>
        </Typography>
      </Box>
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
          sx={spinnerAlwaysVisible}
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