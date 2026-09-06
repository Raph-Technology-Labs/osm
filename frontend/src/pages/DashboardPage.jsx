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
import MainLayout from "../layouts/MainLayout";

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
  const [timeFilter, setTimeFilter] = useState("today");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [stats, setStats] = useState(null);
  const [stationBreakdown, setStationBreakdown] = useState([]);
  const [defectBreakdown, setDefectBreakdown] = useState([]);
  const [sessions, setSessions] = useState({ total: 0, data: [] });
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);

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

  const handleDownload = async () => {
    const { data } = await api.get("/dashboard/download-report", {
      params: filterParams(),
      responseType: "blob",
    });
    const url = window.URL.createObjectURL(new Blob([data], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `osm_report_${timeFilter}.csv`);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  return (
    <MainLayout title="Dashboard">
      {/* Filters -- one row, above the charts */}
      <Box sx={{ display: "flex", gap: 2, alignItems: "center", mb: 3, flexWrap: "wrap" }}>
        <Select size="small" value={timeFilter} onChange={(e) => setTimeFilter(e.target.value)} sx={{ minWidth: 140 }}>
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
              onChange={(e) => setStartDate(e.target.value)}
            />
            <TextField
              size="small"
              type="date"
              label="End"
              InputLabelProps={{ shrink: true }}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </>
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="outlined" startIcon={<DownloadIcon />} onClick={handleDownload}>
          Download CSV
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

      {/* Recent sessions table -- also the accessible "table view" of the chart data */}
      <Paper variant="outlined" sx={{ borderRadius: "10px", overflow: "hidden" }}>
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
              {sessions.data.map((s) => (
                <TableRow key={s.session_id}>
                  <TableCell>{s.session_id}</TableCell>
                  <TableCell>
                    {s.part_name} <Typography component="span" variant="caption" sx={{ color: theme.palette.text.secondary }}>({s.part_code})</Typography>
                  </TableCell>
                  <TableCell>{s.session_start ? new Date(s.session_start).toLocaleString() : "—"}</TableCell>
                  <TableCell>{s.session_end ? new Date(s.session_end).toLocaleString() : "in progress"}</TableCell>
                  <TableCell align="right">{s.total_fired}</TableCell>
                  <TableCell align="right" sx={{ color: theme.palette.success.main }}>{s.total_passed}</TableCell>
                  <TableCell align="right" sx={{ color: theme.palette.error.main }}>{s.total_failed}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
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
        />
      </Paper>
    </MainLayout>
  );
};

export default DashboardPage;
