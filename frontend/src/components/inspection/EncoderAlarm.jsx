import { useState } from "react";
import { Alert, AlertTitle, Box } from "@mui/material";

// Revolution-length alarm (warn only). The backend checks, at every
// encoder_indexer_ppr reset, that the revolution counted ~encoder_cpr
// pulses (StationDispatcher._check_revolution_length) and sends the latest
// short revolution on the RingState broadcast as ringState.encoder_alarm.
// Added after 2026-09-24, when a slipped encoder coupling reset at
// ~1500/4800 and silently froze ring tracking -- see docs/incidents/.
//
// Shown until dismissed; a NEW short revolution (higher seq) shows it again.
// Positioned top-center so it never stacks under ConnectionAlerts
// (top-right, global).
const EncoderAlarm = ({ alarm }) => {
  const [dismissedSeq, setDismissedSeq] = useState(0);

  if (!alarm || alarm.seq <= dismissedSeq) return null;

  return (
    <Box
      sx={{
        position: "fixed",
        top: 16,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 2000,
        maxWidth: 560,
      }}
    >
      <Alert
        severity="warning"
        variant="filled"
        onClose={() => setDismissedSeq(alarm.seq)}
        sx={{ boxShadow: 4 }}
      >
        <AlertTitle>Encoder lost pulses</AlertTitle>
        Last revolution counted only {alarm.reached} of {alarm.expected} ({alarm.pct}%,
        minimum {alarm.min_pct}%). Check the encoder coupling and wiring — disc tracking,
        camera triggers and rejects may be wrong.
        {alarm.seq > 1 ? ` (${alarm.seq} short revolutions this session)` : ""}
      </Alert>
    </Box>
  );
};

export default EncoderAlarm;
