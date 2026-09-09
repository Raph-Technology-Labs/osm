import { Box, Card, Chip, Typography, useTheme } from "@mui/material";

// One camera tile: live frame, OK/NOK badge, and whichever detail its
// pipeline produces -- defect name + count (defect stations) or nominal/
// measured/tolerance (measurement stations). A camera with neither
// pipeline (plain pass-through) just shows the OK/NOK badge.
const CameraPlaceholder = ({ cameraId, frame, result }) => {
  const theme = useTheme();
  const hasResult = Boolean(result);
  const passed = result?.passed;
  const measurement = result?.measurement_data?.diameter_mm;

  return (
    <Card sx={{ p: 1.5, borderRadius: "8px", height: "100%" }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
        <Box>
          <Typography sx={{ fontWeight: 600 }}>{cameraId}</Typography>
          {hasResult && result.part_id != null && (
            <Typography variant="caption" sx={{ color: theme.palette.text.secondary }}>
              Part #{result.part_id}
            </Typography>
          )}
        </Box>
        <Chip
          label={hasResult ? (passed ? "OK" : "NOK") : "—"}
          color={hasResult ? (passed ? "success" : "error") : "default"}
          size="small"
          sx={{ fontWeight: 700 }}
        />
      </Box>

      <Box
        sx={{
          width: "100%",
          aspectRatio: "4 / 3",
          bgcolor: theme.palette.grey[900],
          borderRadius: "6px",
          overflow: "hidden",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {frame ? (
          <img src={frame} alt={cameraId} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
        ) : (
          <Typography sx={{ color: theme.palette.grey[500] }}>Waiting for frames…</Typography>
        )}
      </Box>

      {/* Defect detail */}
      {hasResult && result.defect_label && !measurement && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="body2" sx={{ color: theme.palette.error.main, fontWeight: 600 }}>
            {result.defect_label}
            {result.defect_count > 1 ? ` × ${result.defect_count}` : ""}
          </Typography>
          {result.defect_confidence != null && (
            <Typography variant="caption" sx={{ color: theme.palette.text.secondary }}>
              confidence {(result.defect_confidence * 100).toFixed(0)}%
            </Typography>
          )}
        </Box>
      )}

      {/* Measurement detail */}
      {measurement && (
        <Box sx={{ mt: 1 }}>
          <Typography
            variant="body2"
            sx={{ fontWeight: 600, color: measurement.passed ? theme.palette.success.main : theme.palette.error.main }}
          >
            ⌀ {measurement.measured?.toFixed(2)} {measurement.unit || "mm"}
            {measurement.nominal != null && (
              <Typography component="span" variant="caption" sx={{ color: theme.palette.text.secondary, ml: 0.5 }}>
                (nom {measurement.nominal})
              </Typography>
            )}
          </Typography>
          {(measurement.resolved_lower != null || measurement.resolved_upper != null) && (
            <Typography variant="caption" sx={{ color: theme.palette.text.secondary, display: "block" }}>
              size {measurement.resolved_lower ?? "—"}–{measurement.resolved_upper ?? "—"} {measurement.unit || "mm"} —{" "}
              {measurement.passed ? "within tolerance" : "out of tolerance"}
            </Typography>
          )}
          {measurement.ovality_measured != null && (
            <Typography
              variant="caption"
              sx={{
                display: "block",
                color:
                  measurement.max_ovality != null && measurement.ovality_measured > measurement.max_ovality
                    ? theme.palette.error.main
                    : theme.palette.text.secondary,
              }}
            >
              ovality {measurement.ovality_measured.toFixed(2)} {measurement.unit || "mm"}
              {measurement.max_ovality != null && ` (max ${measurement.max_ovality})`}
            </Typography>
          )}
        </Box>
      )}
    </Card>
  );
};

export default CameraPlaceholder;
