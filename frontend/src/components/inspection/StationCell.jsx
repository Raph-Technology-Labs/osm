import { Box, Paper, Typography } from "@mui/material";
import CameraPlaceholder from "./CameraPlaceholder";

// One station's cameras, grouped together -- never split across pages
// (InspectionPage.jsx's pagination groups by station_id for exactly this
// reason).
//
// Fixed-width tracks, not 1fr: a single-camera station stretched across the
// full page gives a 1200px-wide video tile, which reads as a layout bug.
// Tiles stay tile-sized and the row fits as many as there are -- leftover
// space is left empty rather than padded with filler cards.
const TILE_MIN = 300;
const TILE_MAX = 380;

const StationCell = ({ stationId, station, cameras, frames, results, stationTotals }) => {
  // Pass rate comes from this station's persisted SessionResult rows
  // (GET /inspection/session/analysis), not from anything accumulated in the
  // browser -- so it survives a page reload and matches what a report says.
  const ok = stationTotals?.ok || 0;
  const nok = stationTotals?.nok || 0;
  const total = ok + nok;
  const passRate = total ? ((ok / total) * 100).toFixed(1) : null;

  return (
       <Paper
      variant="outlined"
      sx={{
        borderRadius: 2,
        p: 2,
        display: "flex",
        flexDirection: "column",
        gap: 1.25,
        flex: 1,
        minHeight: 0,
        overflow: "hidden",
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, flexWrap: "wrap" }}>
        <Typography sx={{ fontWeight: 700, fontSize: "0.95rem" }}>
          {station?.name || `Station ${stationId}`}
        </Typography>
        <Typography variant="caption" sx={{ color: "text.secondary" }}>
          {stationId}
          {station?.slot_offset != null && ` · offset ${station.slot_offset} slots`}
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        {passRate && (
          <Typography variant="caption" sx={{ color: "text.secondary" }}>
            pass rate {passRate}% ({ok}/{total})
          </Typography>
        )}
      </Box>

       <Box
        sx={{
          display: "flex",
          gap: 1.5,
          flexGrow: 1,
          minHeight: 0,
          alignItems: "stretch",
        }}
      >
        {cameras.map((camId) => (
          <Box key={camId} sx={{ flex: `0 1 ${TILE_MAX}px`, minWidth: 0, minHeight: 0 }}>
            <CameraPlaceholder
              cameraId={camId}
              frame={frames[camId]}
              result={results[camId]}
            />
          </Box>
        ))}
      </Box>
    </Paper>
  );
};

export default StationCell;