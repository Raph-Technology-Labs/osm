import { useEffect, useState, useCallback } from "react";
import {
  Box,
  Paper,
  Typography,
  Select,
  MenuItem,
  TextField,
  Button,
  Table,
  TableHead,
  TableRow,
  TableCell,
  TableBody,
  TablePagination,
  Alert,
  Snackbar,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
  useTheme,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
  LabelList,
} from "recharts";
import api from "../api/axios";

const FORMATS = {
  csv: { label: "CSV", mime: "text/csv" },
  pdf: { label: "PDF", mime: "application/pdf" },
};

// local YYYY-MM-DD, used as the max for date inputs (no future dates)
const todayStr = () => {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

// pull a filename out of Content-Disposition if the backend sends one
const filenameFromHeaders = (headers) => {
  const cd = headers?.["content-disposition"] || "";
  const match = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  return match ? decodeURIComponent(match[1]) : null;
};

// with responseType "blob", error bodies arrive as a Blob too — read the detail
const blobErrorMessage = async (err) => {
  const data = err?.response?.data;
  if (data instanceof Blob) {
    try {
      const text = await data.text();
      const json = JSON.parse(text);
      return json.detail || text;
    } catch {
      return null;
    }
  }
  return err?.response?.data?.detail || null;
};

const fieldLabelSx = { fontSize: "0.875rem", fontWeight: 600, color: "text.primary", mb: 0.5 };

const StatTile = ({ label, value, color }) => {
  const theme = useTheme();
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: "10px", flex: 1, minWidth: 140 }}>
      <Typography variant="caption" sx={{ color: theme.palette.text.secondary }}>
        {label}
      </Typography>
      <Typography variant="h4" sx={{ fontWeight: 700, color: color || theme.palette.text.primary }}>
        {value}
      </Typography>
    </Paper>
  );
};

const DashboardPage = () => {
  const theme = useTheme();
  const [timeFilter, setTimeFilter] = useState("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [stats, setStats] = useState(null);
  const [stationBreakdown, setStationBreakdown] = useState([]);
  const [defectBreakdown, setDefectBreakdown] = useState([]);
  const [sessions, setSessions] = useState({ total: 0, data: [] });
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);

  // download dialog
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [dlStart, setDlStart] = useState("");
  const [dlEnd, setDlEnd] = useState("");
  const [dlFormat, setDlFormat] = useState("csv");
  const [downloading, setDownloading] = useState(false);

  const [toast, setToast] = useState({ open: false, message: "", severity: "error" });
  const notify = (message, severity = "error") => setToast({ open: true, message, severity });

  const filterParams = useCallback(() => {
    const params = { time_filter: timeFilter };
    if (timeFilter === "range") {
      params.start_date = startDate;
      params.end_date = endDate;
    }
    return params;
  }, [timeFilter, startDate, endDate]);

  useEffect(() => {
    if (timeFilter === "range" && (!startDate || !endDate)) return;
    const params = filterParams();

    api.get("/dashboard/stats", { params }).then(({ data }) => setStats(data)).catch(() => {});
    api.get("/dashboard/station-breakdown", { params }).then(({ data }) => setStationBreakdown(data)).catch(() => {});
    api.get("/dashboard/defect-breakdown", { params }).then(({ data }) => setDefectBreakdown(data)).catch(() => {});
    api
      .get("/dashboard/recent-sessions", { params: { ...params, page: page + 1, limit: rowsPerPage } })
      .then(({ data }) => setSessions(data))
      .catch(() => {});
  }, [filterParams, timeFilter, startDate, endDate, page, rowsPerPage]);

  // ===== download =====
  const datesChosen = Boolean(dlStart && dlEnd);
  const rangeError =
    datesChosen && dlStart > dlEnd ? "Start date cannot be after end date." : "";
  const canDownload = datesChosen && !rangeError && !downloading;

  const openDownload = () => {
    // pre-fill with the dashboard's custom range if one is active
    if (timeFilter === "range" && startDate && endDate) {
      setDlStart(startDate);
      setDlEnd(endDate);
    }
    setDownloadOpen(true);
  };

  const closeDownload = () => {
    if (downloading) return; // don't close mid-download
    setDownloadOpen(false);
    setDlStart("");
    setDlEnd("");
    setDlFormat("csv");
  };

  const handleDownload = async () => {
    if (!canDownload) return;
    setDownloading(true);
    try {
      const response = await api.get("/dashboard/download-report", {
        params: {
          time_filter: "range",
          start_date: dlStart,
          end_date: dlEnd,
          format: dlFormat,
        },
        responseType: "blob",
      });

      const blob = new Blob([response.data], { type: FORMATS[dlFormat].mime });
      const filename =
        filenameFromHeaders(response.headers) ||
        `osm_report_${dlStart}_to_${dlEnd}.${dlFormat}`;

      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);

      notify(`${FORMATS[dlFormat].label} report downloaded.`, "success");
      setDownloading(false);
      closeDownload();
    } catch (err) {
      console.error("download failed:", err);
      const detail = await blobErrorMessage(err);
      notify(detail || "Could not download the report. Please try again.");
      setDownloading(false);
    }
  };

  return (
    <Box>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 3 }}>
        Dashboard
      </Typography>

      {/* Filters -- one row, above the charts */}
      <Box sx={{ display: "flex", gap: 2, alignItems: "center", mb: 3, flexWrap: "wrap" }}>
        <Select
          size="small"
          value={timeFilter}
          onChange={(e) => {
            setTimeFilter(e.target.value);
            setPage(0);
          }}
          sx={{ minWidth: 140 }}
        >
          <MenuItem value="today">Today</MenuItem>
          <MenuItem value="month">This Month</MenuItem>
          <MenuItem value="all">All Time</MenuItem>
          <MenuItem value="range">Custom Range</MenuItem>
        </Select>
        {timeFilter === "range" && (
          <>
            <TextField
              size="small"
              type="date"
              label="Start"
              InputLabelProps={{ shrink: true }}
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value);
                setPage(0);
              }}
            />
            <TextField
              size="small"
              type="date"
              label="End"
              InputLabelProps={{ shrink: true }}
              value={endDate}
              onChange={(e) => {
                setEndDate(e.target.value);
                setPage(0);
              }}
            />
          </>
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="contained" color="primary" startIcon={<DownloadIcon />} onClick={openDownload}>
          Download
        </Button>
      </Box>

      {/* Headline stat tiles */}
      <Box sx={{ display: "flex", gap: 2, mb: 3, flexWrap: "wrap" }}>
        <StatTile label="Sessions" value={stats?.total_sessions ?? "—"} />
        <StatTile label="Parts Fired" value={stats?.total_fired ?? "—"} />
        <StatTile label="Passed" value={stats?.total_passed ?? "—"} color={theme.palette.success.main} />
        <StatTile label="Failed" value={stats?.total_failed ?? "—"} color={theme.palette.error.main} />
        <StatTile
          label="Pass Rate"
          value={stats?.pass_rate != null ? `${(stats.pass_rate * 100).toFixed(1)}%` : "—"}
          color={stats?.pass_rate >= 0.9 ? theme.palette.success.main : theme.palette.warning.main}
        />
      </Box>

      {/* Charts */}
      <Box sx={{ display: "flex", gap: 2, mb: 3, flexWrap: "wrap" }}>
        <Paper variant="outlined" sx={{ p: 2, borderRadius: "10px", flex: 1, minWidth: 340 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
            Pass / Fail by Station
          </Typography>
          {/* Grouped (not stacked) bars, deliberately: validate_palette.js
              scores this success/error pair's CVD separation at 5.4,
              below even the "legal with secondary encoding" 6-8 floor for
              stacked/adjacent-touching segments. Grouped bars add real
              spacing, and LabelList adds direct value labels, so reading
              this never depends on distinguishing the two hues alone. */}
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={stationBreakdown} barGap={6}>
              <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} vertical={false} />
              <XAxis dataKey="station_id" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
              <Tooltip />
              <Legend />
              <Bar dataKey="passed" name="Passed" fill={theme.palette.success.main} radius={[4, 4, 0, 0]}>
                <LabelList dataKey="passed" position="top" style={{ fontSize: 11, fill: theme.palette.text.primary }} />
              </Bar>
              <Bar dataKey="failed" name="Failed" fill={theme.palette.error.main} radius={[4, 4, 0, 0]}>
                <LabelList dataKey="failed" position="top" style={{ fontSize: 11, fill: theme.palette.text.primary }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Paper>

        <Paper variant="outlined" sx={{ p: 2, borderRadius: "10px", flex: 1, minWidth: 340 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
            Defect Frequency
          </Typography>
          {defectBreakdown.length === 0 ? (
            <Typography variant="body2" sx={{ color: theme.palette.text.secondary, py: 4, textAlign: "center" }}>
              No defects in this period.
            </Typography>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={defectBreakdown} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 12 }} allowDecimals={false} />
                <YAxis type="category" dataKey="defect_label" tick={{ fontSize: 12 }} width={90} />
                <Tooltip />
                <Bar dataKey="count" name="Count" fill={theme.palette.primary.main} radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Paper>
      </Box>

      {/* Recent sessions table -- pagination on top */}
      <Paper variant="outlined" sx={{ borderRadius: "10px", overflow: "hidden" }}>
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            pl: 2,
            borderBottom: `1px solid ${theme.palette.divider}`,
          }}
        >
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            Recent Sessions
          </Typography>
          <TablePagination
            component="div"
            count={sessions.total}
            page={page}
            onPageChange={(_e, newPage) => setPage(newPage)}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={(e) => {
              setRowsPerPage(parseInt(e.target.value, 10));
              setPage(0);
            }}
            rowsPerPageOptions={[10, 20, 50]}
            sx={{ borderBottom: "none" }}
          />
        </Box>

        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Session</TableCell>
                <TableCell>Part</TableCell>
                <TableCell>Start</TableCell>
                <TableCell>End</TableCell>
                <TableCell align="right">Fired</TableCell>
                <TableCell align="right">Passed</TableCell>
                <TableCell align="right">Failed</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sessions.data.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} align="center" sx={{ py: 5, color: "text.secondary" }}>
                    No sessions in this period.
                  </TableCell>
                </TableRow>
              ) : (
                sessions.data.map((s) => (
                  <TableRow key={s.session_id}>
                    <TableCell>{s.session_id}</TableCell>
                    <TableCell>
                      {s.part_name}{" "}
                      <Typography component="span" variant="caption" sx={{ color: theme.palette.text.secondary }}>
                        ({s.part_code})
                      </Typography>
                    </TableCell>
                    <TableCell>{s.session_start ? new Date(s.session_start).toLocaleString() : "—"}</TableCell>
                    <TableCell>{s.session_end ? new Date(s.session_end).toLocaleString() : "in progress"}</TableCell>
                    <TableCell align="right">{s.total_fired}</TableCell>
                    <TableCell align="right" sx={{ color: theme.palette.success.main }}>
                      {s.total_passed}
                    </TableCell>
                    <TableCell align="right" sx={{ color: theme.palette.error.main }}>
                      {s.total_failed}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </Box>
      </Paper>

      {/* ===== Download dialog ===== */}
      <Dialog
        open={downloadOpen}
        onClose={closeDownload}
        maxWidth="xs"
        fullWidth
        PaperProps={{ sx: { borderRadius: "12px" } }}
      >
        <DialogTitle sx={{ fontWeight: 700, pb: 0.5 }}>
          Download Report
          <Typography variant="body2" sx={{ color: "text.secondary", fontWeight: 400, mt: 0.5 }}>
            Select a date range, then choose a format
          </Typography>
        </DialogTitle>

        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2.5, pt: "16px !important" }}>
          <Box sx={{ display: "flex", gap: 2 }}>
            <Box sx={{ flex: 1 }}>
              <Typography sx={fieldLabelSx}>From</Typography>
              <TextField
                type="date"
                size="small"
                fullWidth
                value={dlStart}
                onChange={(e) => setDlStart(e.target.value)}
                inputProps={{ max: dlEnd || todayStr() }}
              />
            </Box>
            <Box sx={{ flex: 1 }}>
              <Typography sx={fieldLabelSx}>To</Typography>
              <TextField
                type="date"
                size="small"
                fullWidth
                value={dlEnd}
                onChange={(e) => setDlEnd(e.target.value)}
                inputProps={{ min: dlStart || undefined, max: todayStr() }}
                error={Boolean(rangeError)}
              />
            </Box>
          </Box>

          {rangeError && (
            <Typography variant="caption" sx={{ color: "error.main", mt: -1.5 }}>
              {rangeError}
            </Typography>
          )}

          <Box>
            <Typography sx={{ ...fieldLabelSx, color: datesChosen ? "text.primary" : "text.disabled" }}>
              Format
            </Typography>
            <TextField
              select
              size="small"
              fullWidth
              value={dlFormat}
              onChange={(e) => setDlFormat(e.target.value)}
              disabled={!datesChosen || Boolean(rangeError)}
              helperText={!datesChosen ? "Pick both dates first" : " "}
            >
              {Object.entries(FORMATS).map(([value, { label }]) => (
                <MenuItem key={value} value={value}>
                  {label}
                </MenuItem>
              ))}
            </TextField>
          </Box>
        </DialogContent>

        <DialogActions sx={{ px: 3, pb: 2.5, gap: 1 }}>
          <Button
            onClick={closeDownload}
            disabled={downloading}
            sx={{ color: "text.secondary", textTransform: "none" }}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            color="primary"
            onClick={handleDownload}
            disabled={!canDownload}
            startIcon={downloading ? <CircularProgress size={16} color="inherit" /> : <DownloadIcon />}
            sx={{ textTransform: "none", minWidth: 140 }}
          >
            {downloading ? "Preparing…" : `Download ${FORMATS[dlFormat].label}`}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={toast.open}
        autoHideDuration={4000}
        onClose={() => setToast((t) => ({ ...t, open: false }))}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert
          severity={toast.severity}
          onClose={() => setToast((t) => ({ ...t, open: false }))}
          sx={{ width: "100%" }}
        >
          {toast.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default DashboardPage;