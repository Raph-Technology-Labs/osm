import { Box, Chip, Paper, Typography } from "@mui/material";
import CameraPlaceholder from "./CameraPlaceholder";

// One station's cameras, grouped together -- never split across pages
// (InspectionPage.jsx's pagination groups by station_id for exactly this
// reason).
//
// The grid is fixed 3-up so a station with one camera doesn't stretch that
// tile across the whole row: the empty slots are placeholders, matching the
// operator-screen layout. More than 3 cameras wrap to a new row.
const SLOT_TARGET = 3;

const StationCell = ({ stationId, station, cameras, frames, results, tally }) => {
  const counted = cameras.reduce(
    (acc, id) => {
      const c = tally?.perCamera?.[id];
      return c ? { ok: acc.ok + c.ok, nok: acc.nok + c.nok } : acc;
    },
    { ok: 0, nok: 0 },
  );
  const total = counted.ok + counted.nok;
  const passRate = total ? ((counted.ok / total) * 100).toFixed(1) : null;

  // Which pipeline this station runs, for the tile chips. Comes straight
  // from /inspection/config -- not inferred from results.
  const pipeline = station?.pipeline || station?.type;
  const emptySlots = Math.max(0, SLOT_TARGET - cameras.length);

  return (
    <Paper
      variant="outlined"
      sx={{ borderRadius: 2, p: 2, mb: 2, display: "flex", flexDirection: "column", gap: 1.5 }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, flexWrap: "wrap" }}>
        <Typography sx={{ fontWeight: 700, fontSize: "0.95rem" }}>
          {station?.name || `Station ${stationId}`}
        </Typography>
        <Typography variant="caption" sx={{ color: "text.secondary" }}>
          {stationId}
          {station?.slot_offset != null && ` · offset ${station.slot_offset} slots`}
        </Typography>
        {pipeline && (
          <Chip
            size="small"
            label={pipeline}
            sx={{
              height: 20,
              fontSize: "0.65rem",
              fontWeight: 600,
              bgcolor: pipeline === "defect" ? "error.light" : "info.light",
              color: pipeline === "defect" ? "error.dark" : "info.dark",
            }}
          />
        )}
        <Box sx={{ flexGrow: 1 }} />
        {passRate && (
          <Typography variant="caption" sx={{ color: "text.secondary" }}>
            pass rate {passRate}%
          </Typography>
        )}
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: `repeat(${SLOT_TARGET}, 1fr)`,
          gap: 1.5,
        }}
      >
        {cameras.map((camId) => (
          <CameraPlaceholder
            key={camId}
            cameraId={camId}
            frame={frames[camId]}
            result={results[camId]}
            pipeline={pipeline}
          />
        ))}
        {Array.from({ length: emptySlots }, (_, i) => (
          <Box
            key={`empty-${i}`}
            sx={{
              border: "1px dashed",
              borderColor: "divider",
              borderRadius: 2,
              minHeight: 180,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "text.disabled",
              fontSize: "0.75rem",
              textAlign: "center",
              px: 2,
            }}
          >
            empty slot keeps the grid 3-up
          </Box>
        ))}
      </Box>
    </Paper>
  );
};

export default StationCell;