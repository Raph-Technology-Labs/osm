import { useState } from "react";
import { Alert, AlertTitle, Box } from "@mui/material";

// Indexer tracking alarms, from the RingState broadcast:
//
// * encoder_alarm (warn only) -- the backend checks, at every
//   encoder_indexer_ppr reset, that the revolution counted ~encoder_cpr
//   pulses (StationDispatcher._check_revolution_length). Added after
//   2026-09-24, when a slipped encoder coupling reset at ~1500/4800 and
//   silently froze ring tracking.
// * plc_outage -- the PLC link dropped long enough that the disc may have
//   turned more than half a revolution unseen
//   (StationDispatcher._on_plc_recovered), so slot tracking and capture /
//   reject timing can't be trusted until the session is restarted. The
//   outage itself is shown by ConnectionAlerts (health polling); this is
//   the "tracking is now wrong" consequence. Added 2026-09-28.
//
// Each is shown until dismissed; a NEW occurrence (higher seq) shows it
// again. Stacked top-center so they never sit under ConnectionAlerts
// (top-right, global). See docs/incidents/.
const EncoderAlarm = ({ alarm, plcOutage }) => {
  const [dismissedEncoderSeq, setDismissedEncoderSeq] = useState(0);
  const [dismissedOutageSeq, setDismissedOutageSeq] = useState(0);

  const showEncoder = alarm && alarm.seq > dismissedEncoderSeq;
  const showOutage = plcOutage && plcOutage.seq > dismissedOutageSeq;
  if (!showEncoder && !showOutage) return null;

  return (
    <Box
      sx={{
        position: "fixed",
        top: 16,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 2000,
        maxWidth: 560,
        display: "flex",
        flexDirection: "column",
        gap: 1,
      }}
    >
      {showOutage && (
        <Alert
          severity="error"
          variant="filled"
          onClose={() => setDismissedOutageSeq(plcOutage.seq)}
          sx={{ boxShadow: 4 }}
        >
          <AlertTitle>Disc tracking lost — restart the session</AlertTitle>
          The PLC was unreachable for {plcOutage.outage_s} s; the disc may have moved about{" "}
          {plcOutage.est_pulses} pulses (more than half a revolution) without being seen. Slot
          tracking, camera triggers and rejects are unreliable until you stop and restart the
          session.
        </Alert>
      )}
      {showEncoder && (
        <Alert
          severity="warning"
          variant="filled"
          onClose={() => setDismissedEncoderSeq(alarm.seq)}
          sx={{ boxShadow: 4 }}
        >
          <AlertTitle>Encoder lost pulses</AlertTitle>
          Last revolution counted only {alarm.reached} of {alarm.expected} ({alarm.pct}%,
          minimum {alarm.min_pct}%). Check the encoder coupling and wiring — disc tracking,
          camera triggers and rejects may be wrong.
          {alarm.seq > 1 ? ` (${alarm.seq} short revolutions this session)` : ""}
        </Alert>
      )}
    </Box>
  );
};

export default EncoderAlarm;
