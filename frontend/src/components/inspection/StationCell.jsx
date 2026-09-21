import { useEffect, useState } from "react";
import { Box, IconButton, Paper, Typography, useTheme } from "@mui/material";
import CameraPlaceholder from "./CameraPlaceholder";
import useGridCapacity from "../../hooks/useGridCapacity";

// A camera tile below this is not readable across a shop floor -- it is a
// thumbnail, and a thumbnail of a defect is worse than useless because it
// looks like information without being any. Tiles shrink down to here and
// then stop; the overflow pages instead.
const MIN_TILE_W = 260;
const MIN_TILE_H = 200;

// And a cap at the other end: without it a one-camera station stretches its
// tile across the whole panel, which reads as a layout bug. A maximum is safe
// where a minimum would not be -- a minimum can force overflow, a maximum can
// only leave space empty.
const TILE_MAX = 340;

// A colour per station, generated rather than picked from a list -- a fixed
// palette runs out and starts repeating, and two stations sharing a colour is
// worse than no colour at all.
//
// The golden angle (137.5°) is what a sunflower uses to pack seeds: step the
// hue by it and successive values land as far from each other as possible, for
// ANY count. Station 9 is as distinguishable from station 8 as station 2 is
// from station 1.
//
// It is spent on the station NAME only. A coloured frame around the whole card
// competes with the OK/NOK border on the tile inside it, and the tile is the
// thing an operator needs to catch.
const GOLDEN_ANGLE = 137.508;

// Two hue bands are steered around: green (~95-155) and red (~345-20) mean OK
// and NOK on this screen. A station named in green would read as a passing
// station, so identity colour must never borrow from state colour.
const avoidStateHues = (hue) => {
  if (hue >= 95 && hue <= 155) return hue + 62;
  if (hue >= 345 || hue <= 20) return (hue + 40) % 360;
  return hue;
};

const stationColor = (index, isDark) => {
  const i = index < 0 ? 0 : index;
  const hue = avoidStateHues((205 + i * GOLDEN_ANGLE) % 360); // start on blue
  // Dark mode needs lighter, less saturated ink to stay readable on a dark
  // ground; light mode needs it deeper to hold contrast on white.
  return isDark ? `hsl(${hue}, 62%, 63%)` : `hsl(${hue}, 64%, 42%)`;
};

const StationCell = ({
  stationId,
  station,
  cameras,
  frames,
  results,
  stationTotals,
  index = 0,
}) => {
  const theme = useTheme();
  const accent = stationColor(index, theme.palette.mode === "dark");

  // Pass rate comes from this station's persisted SessionResult rows
  // (GET /inspection/session/analysis), not from anything accumulated in the
  // browser -- so it survives a page reload and matches what a report says.
  const ok = stationTotals?.ok || 0;
  const nok = stationTotals?.nok || 0;
  const total = ok + nok;
  const passRate = total ? ((ok / total) * 100).toFixed(1) : null;

  const { ref, cols, capacity } = useGridCapacity(MIN_TILE_W, MIN_TILE_H);
  const [page, setPage] = useState(0);

  const pageCount = Math.max(1, Math.ceil(cameras.length / capacity));

  // The panel can be resized (or a station added) while a later page is
  // showing -- capacity grows, that page stops existing. Clamp rather than
  // render nothing.
  useEffect(() => {
    if (page > pageCount - 1) setPage(0);
  }, [pageCount, page]);

  const visible = cameras.slice(page * capacity, page * capacity + capacity);

  return (
    <Paper
      variant="outlined"
      sx={{
        borderRadius: 2,
        p: 1.5,
        display: "flex",
        flexDirection: "column",
        gap: 1,
        flex: 1,
        minHeight: 0,
        minWidth: 0,
        overflow: "hidden",
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, flexShrink: 0 }}>
        <Typography sx={{ fontWeight: 700, fontSize: "0.95rem", color: accent }}>
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

        {/* Only appears when cameras actually overflow -- a pager on a
            2-camera station would be a control that does nothing. */}
        {pageCount > 1 && (
          <>
            <IconButton size="small" onClick={() => setPage((p) => (p - 1 + pageCount) % pageCount)}>
              ‹
            </IconButton>
            <Typography variant="caption" sx={{ color: "text.secondary", fontWeight: 700 }}>
              cams {page + 1}/{pageCount}
            </Typography>
            <IconButton size="small" onClick={() => setPage((p) => (p + 1) % pageCount)}>
              ›
            </IconButton>
          </>
        )}
      </Box>

      {/* ref measures what the cascade actually left; cols comes back from
          that measurement, so the grid is always as wide as it can be while
          every tile clears the floor. Rows are min-content, not 1fr: the tile
          takes the height its 4:3 frame asks for instead of stretching into a
          tall black column when a station has only one camera. */}
      <Box
        ref={ref}
        sx={{
          display: "grid",
          gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
          gridAutoRows: "min-content",
          alignContent: "start",
          maxWidth: cols * TILE_MAX,
          gap: 1,
          flexGrow: 1,
          minHeight: 0,
          overflow: "hidden",
        }}
      >
        {visible.map((camId) => (
          <Box key={camId} sx={{ minWidth: 0, minHeight: 0 }}>
            <CameraPlaceholder cameraId={camId} frame={frames[camId]} result={results[camId]} />
          </Box>
        ))}
      </Box>
    </Paper>
  );
};

export default StationCell;