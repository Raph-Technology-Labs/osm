import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import api from "../../api/axios";

// The session report, on screen. Same rows the CSV export writes
// (GET /inspection/session/report), fetched through /session/events so the
// dialog and the file can never disagree about what happened.
//
// Opened on demand rather than polled: this is a record to read, not a live
// feed -- the live feed is the station tiles behind it.
const LIMIT = 500;

const SessionReport = ({ open, onClose }) => {
  const [events, setEvents] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError("");
    Promise.all([
      api.get("/inspection/session/events", { params: { limit: LIMIT } }),
      api.get("/inspection/session/analysis"),
    ])
      .then(([ev, an]) => {
        setEvents(ev.data.events || []);
        setAnalysis(an.data);
      })
      .catch((e) => setError(e?.response?.data?.detail || "Could not load the report."))
      .finally(() => setLoading(false));
  }, [open]);

  // The browser can't send an Authorization header on a plain link, so the
  // CSV is fetched as a blob and handed to a synthetic anchor.
  const handleDownload = async () => {
    try {
      const res = await api.get("/inspection/session/report", { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `osm_session_${analysis?.session_id ?? "report"}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setError(e?.response?.data?.detail || "Could not download the report.");
    }
  };

  const verdict = (e) => {
    if (e.rejected) return { label: "REJECTED", color: "error" };
    if (e.camera_passed === false || e.overall_passed === false)
      return { label: "NOK", color: "error" };
    if (e.camera_passed === true || e.overall_passed === true)
      return { label: "OK", color: "success" };
    return { label: "—", color: "default" };
  };

  const stations = Object.entries(analysis?.stations || {});

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle sx={{ fontWeight: 700, pb: 1 }}>
        Session report
        {analysis?.session_id != null && (
          <Typography component="span" variant="body2" sx={{ color: "text.secondary", ml: 1 }}>
            session #{analysis.session_id}
          </Typography>
        )}
      </DialogTitle>

      <DialogContent dividers>
        {loading && (
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            Loading…
          </Typography>
        )}

        {error && (
          <Typography variant="body2" color="error">
            {error}
          </Typography>
        )}

        {!loading && !error && (
          <>
            {/* Per-station summary first: the shape of the run, before the
                part-by-part detail underneath it. */}
            {stations.length > 0 && (
              <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", mb: 2 }}>
                {stations.map(([id, s]) => {
                  const total = s.ok + s.nok;
                  return (
                    <Box
                      key={id}
                      sx={{
                        px: 2,
                        py: 1,
                        borderRadius: 1.5,
                        border: 1,
                        borderColor: "divider",
                        minWidth: 150,
                      }}
                    >
                      <Typography variant="caption" sx={{ color: "text.secondary" }}>
                        {id}
                      </Typography>
                      <Typography sx={{ fontWeight: 700 }}>
                        {s.ok} OK · {s.nok} NOK
                      </Typography>
                      <Typography variant="caption" sx={{ color: "text.secondary" }}>
                        {total ? `${((s.ok / total) * 100).toFixed(1)}% pass` : "no parts yet"}
                        {s.rejected ? ` · ${s.rejected} rejected` : ""}
                      </Typography>
                    </Box>
                  );
                })}
              </Box>
            )}

            {events.length === 0 ? (
              <Typography variant="body2" sx={{ color: "text.secondary" }}>
                Nothing recorded for this session yet.
              </Typography>
            ) : (
              <Box sx={{ maxHeight: "55vh", overflowY: "auto" }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      {["Time", "Part #", "Station", "Camera", "Pipeline", "Detail", "Result"].map(
                        (h) => (
                          <TableCell key={h} sx={{ fontWeight: 700, fontSize: "0.75rem" }}>
                            {h}
                          </TableCell>
                        ),
                      )}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {events.map((e, i) => {
                      const v = verdict(e);
                      return (
                        <TableRow key={`${e.session_result_id}-${e.camera_id || "agg"}-${i}`}>
                          <TableCell sx={{ fontSize: "0.75rem" }}>
                            {e.fired_at ? new Date(e.fired_at).toLocaleTimeString() : "—"}
                          </TableCell>
                          <TableCell sx={{ fontSize: "0.75rem" }}>{e.ring_part_id}</TableCell>
                          <TableCell sx={{ fontSize: "0.75rem" }}>{e.station_id}</TableCell>
                          <TableCell sx={{ fontSize: "0.75rem" }}>{e.camera_id || "—"}</TableCell>
                          <TableCell sx={{ fontSize: "0.75rem" }}>{e.pipeline}</TableCell>
                          <TableCell sx={{ fontSize: "0.75rem" }}>{e.detail || "—"}</TableCell>
                          <TableCell>
                            <Chip
                              size="small"
                              label={v.label}
                              color={v.color}
                              sx={{ height: 20, fontWeight: 700, fontSize: "0.65rem" }}
                            />
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </Box>
            )}

            <Typography variant="caption" sx={{ color: "text.secondary", display: "block", mt: 1 }}>
              Newest first, last {LIMIT} fires. Rows sharing a part # are the same physical part.
              A session still running is a snapshot, not a final record.
            </Typography>
          </>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 2, gap: 1 }}>
        <Button onClick={onClose} sx={{ color: "text.secondary", textTransform: "none" }}>
          Close
        </Button>
        <Button
          variant="contained"
          startIcon={<DownloadIcon />}
          onClick={handleDownload}
          disabled={loading || !!error}
          sx={{ textTransform: "none" }}
        >
          Download CSV
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default SessionReport;