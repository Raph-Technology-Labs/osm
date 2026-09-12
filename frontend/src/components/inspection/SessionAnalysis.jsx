import { Box, LinearProgress, Paper, Typography } from "@mui/material";

// The right-hand analysis column, split into two exports so the caller can
// put the headline totals ABOVE the digital twin and the breakdown below it.
//
// TWO DIFFERENT SOURCES, deliberately kept as separate cards:
//   SessionTotals     -> ringState (backend, authoritative, one count per
//                        physical part resolved at exit/r1)
//   SessionBreakdown  -> useResultTally, i.e. only what has streamed past
//                        since this page was opened. The backend exposes no
//                        per-defect-class or per-pipeline totals yet; when it
//                        does, swap the tally out for it.
// They will not agree after a page reload, and that is expected — which is
// why the second says so on its face.

const Row = ({ label, value, color }) => (
  <Box sx={{ display: "flex", justifyContent: "space-between", py: 0.4 }}>
    <Typography variant="body2" sx={{ color: "text.secondary" }}>
      {label}
    </Typography>
    <Typography variant="body2" sx={{ fontWeight: 700, color: color || "text.primary" }}>
      {value}
    </Typography>
  </Box>
);

export const SessionTotals = ({ ringState }) => {
  const ok = ringState?.ok_total || 0;
  const nok = ringState?.nok_total || 0;
  const total = ok + nok;
  const passPct = total ? (ok / total) * 100 : 0;

  return (
    <Paper variant="outlined" sx={{ borderRadius: 2, p: 2 }}>
      <Typography sx={{ fontWeight: 700, fontSize: "0.9rem" }}>Session analysis</Typography>
      <Typography variant="caption" sx={{ color: "text.secondary" }}>
        Updates on every exit-station decision
      </Typography>

      <Box sx={{ display: "flex", gap: 1, mt: 1.5 }}>
        {[
          { label: "OK", value: ok, bg: "success.light", fg: "success.dark" },
          { label: "NOK", value: nok, bg: "error.light", fg: "error.dark" },
          { label: "Total", value: total, bg: "action.hover", fg: "text.primary" },
        ].map((s) => (
          <Box
            key={s.label}
            sx={{ flex: 1, textAlign: "center", py: 1.5, borderRadius: 1.5, bgcolor: s.bg }}
          >
            <Typography
              variant="caption"
              sx={{ color: s.fg, fontWeight: 700, letterSpacing: "0.04em" }}
            >
              {s.label}
            </Typography>
            <Typography sx={{ fontWeight: 800, color: s.fg, fontSize: "1.6rem", lineHeight: 1.2 }}>
              {s.value}
            </Typography>
          </Box>
        ))}
      </Box>

      <LinearProgress
        variant="determinate"
        value={passPct}
        color="success"
        sx={{ mt: 1.5, height: 6, borderRadius: 3 }}
      />
      <Typography variant="caption" sx={{ color: "text.secondary" }}>
        {passPct.toFixed(1)}% pass
      </Typography>
    </Paper>
  );
};

const SessionBreakdown = ({ tally }) => {
  const defectEntries = Object.entries(tally?.defects || {}).sort((a, b) => b[1] - a[1]);
  const m = tally?.measurement || { ok: 0, nok: 0 };
  const mTotal = m.ok + m.nok;

  return (
    <>
      <Paper variant="outlined" sx={{ borderRadius: 2, p: 2 }}>
        <Typography sx={{ fontWeight: 700, fontSize: "0.85rem", mb: 0.5 }}>Defect</Typography>
        {defectEntries.length ? (
          defectEntries.map(([label, count]) => (
            <Row key={label} label={label} value={count} color="error.main" />
          ))
        ) : (
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            No defects detected yet.
          </Typography>
        )}
        <Typography variant="caption" sx={{ color: "text.secondary", display: "block", mt: 1 }}>
          Counted since this page was opened, not since the session started.
        </Typography>
      </Paper>

      <Paper variant="outlined" sx={{ borderRadius: 2, p: 2 }}>
        <Typography sx={{ fontWeight: 700, fontSize: "0.85rem", mb: 0.5 }}>Measurement</Typography>
        {mTotal ? (
          <>
            <Row label="Within tolerance" value={m.ok} color="success.main" />
            <Row label="Out of tolerance" value={m.nok} color="error.main" />
            <Row label="Total measured" value={mTotal} />
          </>
        ) : (
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            No measurements yet.
          </Typography>
        )}
        <Typography variant="caption" sx={{ color: "text.secondary", display: "block", mt: 1 }}>
          Counted since this page was opened, not since the session started.
        </Typography>
      </Paper>
    </>
  );
};

export default SessionBreakdown;