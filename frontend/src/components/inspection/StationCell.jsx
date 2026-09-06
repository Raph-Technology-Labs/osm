import { Box, Paper, Typography, useTheme } from "@mui/material";
import CameraPlaceholder from "./CameraPlaceholder";

// One station's cameras, grouped together -- never split across pages
// (InspectionPage.jsx's pagination groups by station_id for exactly this
// reason). More than 4 cameras in one station stacks into a sub-grid
// rather than shrinking tiles below a legible size.
const StationCell = ({ stationId, cameras, frames, results }) => {
  const theme = useTheme();
  const manyCarameras = cameras.length > 4;

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        borderRadius: "10px",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        gap: 1.5,
      }}
    >
      <Typography variant="subtitle1" sx={{ fontWeight: 700, color: theme.palette.text.primary }}>
        Station {stationId}
      </Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: manyCarameras
            ? "repeat(auto-fit, minmax(160px, 1fr))"
            : `repeat(${Math.max(cameras.length, 1)}, 1fr)`,
          gap: 1.5,
          flexGrow: 1,
        }}
      >
        {cameras.map((camId) => (
          <CameraPlaceholder key={camId} cameraId={camId} frame={frames[camId]} result={results[camId]} />
        ))}
      </Box>
    </Paper>
  );
};

export default StationCell;
