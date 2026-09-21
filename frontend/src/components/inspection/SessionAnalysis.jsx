import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import api from "../../api/axios";
import SessionReport from "./SessionReport";

// The session-analysis pieces, split into separate exports so the caller can
// place each one where it reads best:
//
//   SessionTotalsStrip -> full-width band ABOVE the camera grid. Big numbers,
//                         no controls -- readable across the room.
//   ReportActions      -> View / Export, in the rail above the digital twin.
//   SessionTotals      -> the same totals as a narrow rail card (kept for
//                         layouts with no wide band to spare).
//   SessionBreakdown   -> defect/measurement detail, below the digital twin.
//
// TWO DIFFERENT SOURCES, deliberately kept apart:
//   totals    -> ringState (backend, per-tick, one count per physical part
//                resolved at exit/r1)
//   breakdown -> GET /inspection/session/analysis, i.e. the persisted
//                CameraResult/SessionResult rows.
// They can differ by a fraction of a second while results_writer's queue
// drains. Both are backend truth; neither is reconstructed in the browser.
//
// No icon imports here on purpose: @mui/icons-material versions drift between
// installs and a missing export renders as an invalid element, which is a
// confusing failure for a decorative glyph. Text labels say it anyway.

// --- shared -----------------------------------------------------------------

// One endpoint, two representations: GET /inspection/session/report?format=
// serves both from the same rows (session_analysis.report_rows), so the
// spreadsheet and the printed page can never tell different stories.
//
// Returns a result rather than swallowing failures. A download that silently
// does nothing is the worst version of this control -- the operator can't tell
// "no session yet" from "the app is broken".
export const downloadReport = async (format = "csv") => {
  try {
    const res = await api.get("/inspection/session/report", {
      params: { format },
      responseType: "blob",
    });
    // The browser can't send an Authorization header on a plain link, so the
    // file is fetched as a blob and handed to a synthetic anchor.
    const url = window.URL.createObjectURL(new Blob([res.data]));
    const a = document.createElement("a");
    a.href = url;
    // The server sets the real filename in Content-Disposition (session id +
    // timestamp); this is the browser's fallback if it can't read that header.
    a.download = `osm_session_report.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    return { ok: true };
  } catch (err) {
    const status = err?.response?.status;
    return {
      ok: false,
      message:
        status === 404 ? "No session to export yet." : "Could not download the report.",
    };
  }
};

const totalsFrom = (ringState) => {
  const ok = ringState?.ok_total || 0;
  const nok = ringState?.nok_total || 0;
  const total = ok + nok;
  return { ok, nok, total, passPct: total ? (ok / total) * 100 : 0 };
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

// --- report actions ---------------------------------------------------------

// These sit next to the digital twin rather than on the totals band: the twin
// is where an operator looks when they want to know what happened, so the way
// to read the whole story belongs in the same column. The band stays pure
// numbers, which is what keeps it legible from a distance.
//
// Modal-with-format rather than a dropdown, matching the dashboard's own
// Download Report flow -- same gesture in both places. No date range here
// though: the dashboard export spans many sessions, this report IS one
// session, so a From/To pair would be a control with nothing to control.
export const ReportActions = () => {
  const [reportOpen, setReportOpen] = useState(false);
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [format, setFormat] = useState("csv");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null); // { severity, message }

  const handleDownload = async () => {
    setBusy(true);
    const res = await downloadReport(format);
    setBusy(false);
    if (res.ok) {
      setToast({ severity: "success", message: "Download started." });
      setDownloadOpen(false);
    } else {
      setToast({ severity: "error", message: res.message });
    }
  };

  return (
    // One Box, not a fragment: the Dialogs mount inside it rather than becoming
    // extra children of the rail's flex column, where they take a gap's worth
    // of space from the digital twin below.
    <Box sx={{ flexShrink: 0 }}>
      {/* View for reading it here, Export for taking it away -- both read the
          same endpoints, so the two can never tell different stories. */}
      <Stack direction="row" spacing={1}>
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
          onClick={() => setDownloadOpen(true)}
          sx={{ flex: 1, textTransform: "none" }}
        >
          Export
        </Button>
      </Stack>

      <Dialog
        open={downloadOpen}
        onClose={() => setDownloadOpen(false)}
        maxWidth="sm"
        fullWidth
        PaperProps={{ sx: { borderRadius: 1, width: 420 } }}
      >
        <DialogTitle sx={{ fontWeight: 700 }}>
          Export report
          <Typography variant="body2" sx={{ color: "#6b7280", mt: 1, fontWeight: 400 }}>
            This run's results, one row per camera
          </Typography>
        </DialogTitle>

        <DialogContent sx={{ bgcolor: "#f9fafb", mt: 1, p: 3, borderRadius: 1 }}>
          <Typography
            sx={{ fontSize: "0.875rem", fontWeight: 600, color: "#111827", mb: 0.5 }}
          >
            Choose Format
          </Typography>
          <TextField
            select
            fullWidth
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            sx={{
              "& .MuiOutlinedInput-root": { borderRadius: 0.5, bgcolor: "#fff", height: 48 },
            }}
          >
            <MenuItem value="csv">CSV</MenuItem>
            <MenuItem value="pdf">PDF</MenuItem>
          </TextField>
        </DialogContent>

        <DialogActions sx={{ p: 3, pt: 0, gap: 2 }}>
          <Button
            variant="outlined"
            onClick={() => setDownloadOpen(false)}
            sx={{ flex: 1, textTransform: "none", borderRadius: 0.5 }}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleDownload}
            disabled={busy}
            sx={{ flex: 1, textTransform: "none", borderRadius: 0.5 }}
          >
            {busy ? "Downloading..." : "Download"}
          </Button>
        </DialogActions>
      </Dialog>

      <SessionReport open={reportOpen} onClose={() => setReportOpen(false)} />

      <Snackbar
        open={Boolean(toast)}
        autoHideDuration={3000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert severity={toast?.severity} sx={{ width: "100%" }} onClose={() => setToast(null)}>
          {toast?.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

// --- wide strip -------------------------------------------------------------

// Counts run from single digits at the start of a shift to six figures by the
// end of one. A fixed size either wastes the space early or overflows late,
// so the size steps down with digit count -- the number stays as large as
// will actually fit. This ladder is for the full-width band.
const stripFontSize = (value) => {
  const digits = String(value ?? "").length;
  if (digits <= 3) return "4.2rem";
  if (digits === 4) return "3.6rem";
  if (digits === 5) return "3.0rem";
  if (digits === 6) return "2.5rem";
  return "2rem";
};

export const SessionTotalsStrip = ({ ringState }) => {
  const { ok, nok, total, passPct } = totalsFrom(ringState);

  const tiles = [
    { label: "OK", value: ok, bg: "success.light", fg: "success.dark" },
    { label: "NOK", value: nok, bg: "error.light", fg: "error.dark" },
    { label: "TOTAL", value: total, bg: "action.hover", fg: "text.primary" },
    { label: "PASS", value: `${passPct.toFixed(1)}%`, bg: "action.hover", fg: "text.primary" },
  ];

  return (
    // flexShrink: 0 -- the band keeps its height and the station area below
    // gives up the difference, so the page still never scrolls.
    <Paper variant="outlined" sx={{ borderRadius: 2, p: 1.5, mb: 1.5, flexShrink: 0 }}>
      <Typography sx={{ fontWeight: 700, fontSize: "0.9rem", mb: 1 }}>Session analysis</Typography>

      <Box sx={{ display: "flex", gap: 1.5 }}>
        {tiles.map((t) => (
          <Box
            key={t.label}
            sx={{
              flex: 1,
              minWidth: 0, // lets a tile shrink instead of forcing the row wider
              textAlign: "center",
              py: 1.25,
              px: 1,
              borderRadius: 2,
              bgcolor: t.bg,
            }}
          >
            <Typography
              sx={{
                color: t.fg,
                fontWeight: 800,
                fontSize: "0.8rem",
                letterSpacing: "0.12em",
                opacity: 0.85,
              }}
            >
              {t.label}
            </Typography>
            <Typography
              sx={{
                fontWeight: 900,
                color: t.fg,
                fontSize: stripFontSize(t.value),
                lineHeight: 1.05,
                // Tabular figures stop the number jittering sideways as it
                // ticks up; nowrap + hidden means a surprise value clips
                // rather than breaking the row apart.
                fontVariantNumeric: "tabular-nums",
                whiteSpace: "nowrap",
                overflow: "hidden",
              }}
            >
              {typeof t.value === "number" ? t.value.toLocaleString() : t.value}
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
    </Paper>
  );
};

// --- narrow rail card (kept for other layouts) ------------------------------

const countFontSize = (value) => {
  const digits = String(value ?? "").length;
  if (digits <= 3) return "2.6rem";
  if (digits === 4) return "2.1rem";
  if (digits === 5) return "1.75rem";
  if (digits === 6) return "1.45rem";
  return "1.2rem";
};

export const SessionTotals = ({ ringState }) => {
  const { ok, nok, total, passPct } = totalsFrom(ringState);

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
              minWidth: 0,
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

      <Box sx={{ mt: 1.5 }}>
        <ReportActions />
      </Box>
    </Paper>
  );
};

// --- breakdown --------------------------------------------------------------

const SessionBreakdown = ({ analysis }) => {
  // `deciding` is the label that actually made a camera NOK -- what an
  // operator acts on. `detected` includes classes the model saw but
  // allowed_defects ignored; shown separately so a drifting model is visible
  // without inflating the failure count.
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
                  <Typography
                    component="span"
                    variant="caption"
                    sx={{ color: "text.secondary", ml: 0.5 }}
                  >
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