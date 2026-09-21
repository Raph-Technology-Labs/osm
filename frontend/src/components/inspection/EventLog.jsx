import { useEffect, useState } from "react";
import {
  Box,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import api from "../../api/axios";

// Station fires as persisted, newest first. Rows sharing a ring_part_id are
// one physical part crossing s1 -> s2 -> exit1, which is what makes a NOK
// traceable back through every station it passed.
//
// Polled rather than streamed: the live tiles above already show the current
// part, this is the history behind it, and a reload must not lose it.
const POLL_MS = 3000;
const LIMIT = 200;

const FILTERS = [
  { key: "all", label: "All" },
  { key: "nok", label: "NOK only" },
  { key: "rejected", label: "Rejected" },
];

const EventLog = () => {
  const [filter, setFilter] = useState("all");
  const [events, setEvents] = useState([]);
  const [available, setAvailable] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const poll = () => {
      api
        .get("/inspection/session/events", {
          params: { limit: LIMIT, only_nok: filter === "nok" },
        })
        .then(({ data }) => {
          if (cancelled) return;
          setAvailable(true);
          // `rejected` is set only on the exit/reject row, so this filter is
          // applied client-side -- the endpoint's only_nok covers the common
          // case without a second query param.
          const rows = data.events || [];
          setEvents(filter === "rejected" ? rows.filter((e) => e.rejected) : rows);
        })
        .catch(() => {
          if (cancelled) return;
          setAvailable(false);
          setEvents([]);
        });
    };

    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [filter]);

  const verdict = (e) => {
    if (e.rejected) return { label: "REJECTED", color: "error" };
    if (e.camera_passed === false || e.overall_passed === false)
      return { label: "NOK", color: "error" };
    if (e.camera_passed === true || e.overall_passed === true)
      return { label: "OK", color: "success" };
    return { label: "—", color: "default" };
  };

  return (
    <Paper variant="outlined" sx={{ borderRadius: 2, p: 2, mb: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
        <Typography sx={{ fontWeight: 700, fontSize: "0.95rem" }}>Event log</Typography>
        <Box sx={{ flexGrow: 1 }} />
        {FILTERS.map((f) => (
          <Chip
            key={f.key}
            size="small"
            label={f.label}
            onClick={() => setFilter(f.key)}
            color={filter === f.key ? "primary" : "default"}
            variant={filter === f.key ? "filled" : "outlined"}
          />
        ))}
      </Stack>

      {!available ? (
        <Typography variant="body2" sx={{ color: "text.secondary" }}>
          No session to show events for.
        </Typography>
      ) : events.length === 0 ? (
        <Typography variant="body2" sx={{ color: "text.secondary" }}>
          No events yet.
        </Typography>
      ) : (
        <Box sx={{ maxHeight: 320, overflowY: "auto" }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                {["Time", "Part #", "Station", "Camera", "Pipeline", "Detail", "Result"].map((h) => (
                  <TableCell key={h} sx={{ fontWeight: 700, fontSize: "0.72rem" }}>
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {events.map((e, i) => {
                const v = verdict(e);
                return (
                  <TableRow key={`${e.session_result_id}-${e.camera_id || "agg"}-${i}`}>
                    <TableCell sx={{ fontSize: "0.72rem" }}>
                      {e.fired_at ? new Date(e.fired_at).toLocaleTimeString() : "—"}
                    </TableCell>
                    <TableCell sx={{ fontSize: "0.72rem" }}>{e.ring_part_id}</TableCell>
                    <TableCell sx={{ fontSize: "0.72rem" }}>{e.station_id}</TableCell>
                    <TableCell sx={{ fontSize: "0.72rem" }}>{e.camera_id || "—"}</TableCell>
                    <TableCell sx={{ fontSize: "0.72rem" }}>{e.pipeline}</TableCell>
                    <TableCell sx={{ fontSize: "0.72rem" }}>{e.detail || "—"}</TableCell>
                    <TableCell>
                      <Chip size="small" label={v.label} color={v.color} sx={{ height: 20, fontWeight: 700, fontSize: "0.65rem" }} />
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
      </Typography>
    </Paper>
  );
};

export default EventLog;