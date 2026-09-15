import { useState } from "react";
import { Box, Button, LinearProgress, Paper, Stack, Typography } from "@mui/material";
import api from "../../api/axios";
import SessionReport from "./SessionReport";

// The right-hand analysis column, split into two exports so the caller can
// put the headline totals ABOVE the digital twin and the breakdown below it.
//
// TWO DIFFERENT SOURCES, deliberately kept as separate cards:
//   SessionTotals     -> ringState (backend, per-tick, one count per physical
//                        part resolved at exit/r1)
//   SessionBreakdown  -> GET /inspection/session/analysis, i.e. the persisted
//                        CameraResult/SessionResult rows.
// They can differ by a fraction of a second while results_writer's queue
// drains. Both are backend truth; neither is reconstructed in the browser.
//
// No icon imports here on purpose: @mui/icons-material versions drift between
// installs and a missing export renders as an invalid element, which is a
// confusing failure for a decorative glyph. Text labels say it anyway.

// Counts run from single digits at the start of a shift to six figures by
// the end of one, in a tile ~100px wide. A fixed size either wastes the
// space early or overflows late, so the size steps down with digit count --
// the number stays as large as will actually fit.
const countFontSize = (value) => {
  const digits = String(value ?? "").length;
  if (digits <= 3) return "2.6rem";
  if (digits === 4) return "2.1rem";
  if (digits === 5) return "1.75rem";
  if (digits === 6) return "1.45rem";
  return "1.2rem";
};

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

  const [reportOpen, setReportOpen] = useState(false);

  // The browser can't send an Authorization header on a plain link, so the
  // CSV is fetched as a blob and handed to a synthetic anchor.
  const handleDownload = async () => {
    try {
      const res = await api.get("/inspection/session/report", { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = "osm_session_report.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch {
      /* no session, or nothing to export */
    }
  };

  return (
    <Paper variant="outlined" sx={{ borderRadius: 2, p: 2 }}>
      <Typography sx={{ fontWeight: 700, fontSize: "0.9rem" }}>Session analysis</Typography>

      <Box sx={{ display: "flex", gap: 1, mt: 1.5 }}>
        {[
          { label: "OK", value: ok, bg: "success.light", fg: "success.dark" },
          { label: "NOK", value: nok, bg: "error.light", fg: "error.dark" },
          { label: "Total", value: total, bg: "action.hover", fg: "text.primary" },
        ].map((s) => (
          <Box
            key={s.label}
            sx={{
              flex: 1,
              minWidth: 0, // lets the tile shrink instead of forcing the row wider
              textAlign: "center",
              py: 1.5,
              px: 0.5,
              borderRadius: 1.5,
              bgcolor: s.bg,
            }}
          >
            <Typography
              variant="caption"
              sx={{ color: s.fg, fontWeight: 700, letterSpacing: "0.04em", display: "block" }}
            >
              {s.label}
            </Typography>
            <Typography
              sx={{
                fontWeight: 800,
                color: s.fg,
                fontSize: countFontSize(s.value),
                lineHeight: 1.15,
                // Tabular figures stop the number jittering sideways as it
                // ticks up; nowrap + hidden means a surprise value clips
                // rather than breaking the row apart.
                fontVariantNumeric: "tabular-nums",
                whiteSpace: "nowrap",
                overflow: "hidden",
              }}
            >
              {s.value.toLocaleString()}
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

      {/* View for reading it here, Download for taking it away -- both read
          the same endpoints, so the two can never tell different stories. */}
      <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
        <Button
          size="small"
          variant="outlined"
          onClick={() => setReportOpen(true)}
          sx={{ flex: 1, textTransform: "none" }}
        >
          View report
        </Button>
        <Button
          size="small"
          variant="outlined"
          onClick={handleDownload}
          sx={{ flex: 1, textTransform: "none" }}
        >
          Download
        </Button>
      </Stack>

      <SessionReport open={reportOpen} onClose={() => setReportOpen(false)} />
    </Paper>
  );
};

const SessionBreakdown = ({ analysis }) => {
  // `deciding` is the label that actually made a camera NOK -- what an
  // operator acts on. `detected` includes classes the model saw but
  // allowed_defects ignored; shown separately so a drifting model is
  // visible without inflating the failure count.
  const deciding = Object.entries(analysis?.defects?.deciding || {});
  const detected = Object.entries(analysis?.defects?.detected || {});
  const ignored = detected.filter(([name]) => !analysis?.defects?.deciding?.[name]);
  const measurements = Object.entries(analysis?.measurements || {});
  const hasSession = analysis?.session_id != null;

  return (
    <>
      <Paper variant="outlined" sx={{ borderRadius: 2, p: 2 }}>
        <Typography sx={{ fontWeight: 700, fontSize: "0.85rem", mb: 0.5 }}>Defect</Typography>
        {deciding.length ? (
          deciding.map(([label, count]) => (
            <Row key={label} label={label} value={count} color="error.main" />
          ))
        ) : (
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            {hasSession ? "No defects recorded yet." : "No session to analyse."}
          </Typography>
        )}

        {ignored.length > 0 && (
          <Box sx={{ mt: 1, pt: 1, borderTop: 1, borderColor: "divider" }}>
            <Typography variant="caption" sx={{ color: "text.secondary" }}>
              Detected but not counted as failures
            </Typography>
            {ignored.map(([label, count]) => (
              <Row key={label} label={label} value={count} />
            ))}
          </Box>
        )}

        {analysis?.defects?.total_cameras > 0 && (
          <Typography variant="caption" sx={{ color: "text.secondary", display: "block", mt: 1 }}>
            {analysis.defects.nok_cameras} of {analysis.defects.total_cameras} camera results NOK
          </Typography>
        )}
      </Paper>

      <Paper variant="outlined" sx={{ borderRadius: 2, p: 2 }}>
        <Typography sx={{ fontWeight: 700, fontSize: "0.85rem", mb: 0.5 }}>Measurement</Typography>
        {measurements.length ? (
          measurements.map(([name, m]) => (
            <Box key={name} sx={{ mb: 1.5, "&:last-of-type": { mb: 0 } }}>
              <Typography variant="body2" sx={{ fontWeight: 700 }}>
                {name}
                {m.nominal != null && (
                  <Typography component="span" variant="caption" sx={{ color: "text.secondary", ml: 0.5 }}>
                    nom {m.nominal} {m.unit}
                  </Typography>
                )}
              </Typography>
              <Row label="Within tolerance" value={m.ok} color="success.main" />
              <Row label="Out of tolerance" value={m.nok} color="error.main" />
              {m.mean != null && (
                <Typography variant="caption" sx={{ color: "text.secondary", display: "block" }}>
                  mean {m.mean} · min {m.min} · max {m.max} {m.unit}
                </Typography>
              )}
            </Box>
          ))
        ) : (
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            {hasSession ? "No measurements recorded yet." : "No session to analyse."}
          </Typography>
        )}
      </Paper>
    </>
  );
};

export default SessionBreakdown;