import { Box, Chip, Paper, Typography, useTheme } from "@mui/material";
import VideocamOutlinedIcon from "@mui/icons-material/VideocamOutlined";

// One camera tile: live frame, OK/NOK badge, and whichever detail its
// pipeline produces -- defect name + count (defect stations) or nominal/
// measured/tolerance (measurement stations). A camera with neither
// pipeline (plain pass-through) just shows the OK/NOK badge.
//
// Styling only, no behaviour change: the card border and footer badge take
// their colour from result.passed so a NOK tile is identifiable across the
// room, which is the whole point of the operator screen.
const CameraPlaceholder = ({ cameraId, frame, result }) => {
  const theme = useTheme();
  const hasResult = Boolean(result);
  const passed = result?.passed;
  const measurement = result?.measurement_data?.diameter_mm;

  const accent = !hasResult
    ? theme.palette.divider
    : passed
      ? theme.palette.success.main
      : theme.palette.error.main;

  return (
    <Paper
      variant="outlined"
      sx={{
        borderRadius: 2,
        borderColor: accent,
        borderWidth: hasResult ? 2 : 1,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
      }}
    >
      {/* Header: camera id, and the part it last reported on */}
      <Box
        sx={{
          px: 1.5,
          py: 0.75,
          display: "flex",
          alignItems: "center",
          gap: 1,
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <Typography sx={{ fontWeight: 700, fontSize: "0.9rem" }}>{cameraId}</Typography>
        <Box sx={{ flexGrow: 1 }} />
        {hasResult && result.part_id != null && (
          <Typography variant="caption" sx={{ color: "text.secondary" }}>
            #{result.part_id}
          </Typography>
        )}
      </Box>

            {/* Live frame, or a standing-by panel until the first one arrives.
          Height-driven, not aspect-ratio-driven: the tile has to fit the
          space the station row has, whatever that is, so this page never
          scrolls. objectFit: contain letterboxes rather than distorting. */}
              <Box
          sx={{
            position: "relative",
            width: "100%",
            aspectRatio: "4 / 3",   // shape the frame, don't let it stretch
            maxHeight: "100%",
            minHeight: 0,
            bgcolor: theme.palette.grey[900],
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
      
        {frame ? (
          <>
            <img
              src={frame}
              alt={cameraId}
              style={{ width: "100%", height: "100%", objectFit: "contain" }}
            />
            <Chip
              size="small"
              label="LIVE"
              sx={{
                position: "absolute",
                top: 6,
                right: 6,
                height: 18,
                fontSize: "0.6rem",
                fontWeight: 700,
                bgcolor: "error.main",
                color: "#fff",
              }}
            />
          </>
        ) : (
          // Standing-by rather than an empty black rectangle: an operator
          // should be able to tell "camera configured, no frames yet" from
          // "something is broken" without asking anyone.
          <Box sx={{ textAlign: "center", px: 2 }}>
            <VideocamOutlinedIcon sx={{ fontSize: 34, color: theme.palette.grey[700] }} />
            <Typography
              sx={{
                color: theme.palette.grey[500],
                fontSize: "0.78rem",
                fontWeight: 600,
                mt: 0.5,
              }}
            >
              Standing by
            </Typography>
            <Typography sx={{ color: theme.palette.grey[600], fontSize: "0.68rem" }}>
              No frames from {cameraId} yet
            </Typography>
          </Box>
        )}
      </Box>

      {/* Footer: pipeline detail on the left, verdict on the right */}
      <Box
        sx={{
          px: 1.5,
          py: 1,
          display: "flex",
          alignItems: "center",
          gap: 1,
          borderTop: 1,
          borderColor: "divider",
          minHeight: 60,
        }}
      >
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          {/* Defect detail */}
          {hasResult && result.defect_label && !measurement && (
            <>
              <Typography
                variant="body2"
                sx={{ color: theme.palette.error.main, fontWeight: 700 }}
                noWrap
              >
                {result.defect_label}
                {result.defect_count > 1 ? ` × ${result.defect_count}` : ""}
              </Typography>
              {result.defect_confidence != null && (
                <Typography variant="caption" sx={{ color: "text.secondary" }}>
                  confidence {(result.defect_confidence * 100).toFixed(0)}%
                </Typography>
              )}
            </>
          )}

          {hasResult && !result.defect_label && !measurement && (
            <Typography variant="body2" sx={{ color: "text.secondary" }} noWrap>
              No defect above threshold
            </Typography>
          )}

          {/* Measurement detail */}
          {measurement && (
            <>
              <Typography
                variant="body2"
                sx={{
                  fontWeight: 700,
                  color: measurement.passed
                    ? theme.palette.success.main
                    : theme.palette.error.main,
                }}
                noWrap
              >
                ⌀ {measurement.measured?.toFixed(2)} {measurement.unit || "mm"}
                {measurement.nominal != null && (
                  <Typography
                    component="span"
                    variant="caption"
                    sx={{ color: "text.secondary", ml: 0.5 }}
                  >
                    (nom {measurement.nominal})
                  </Typography>
                )}
              </Typography>
              {(measurement.resolved_lower != null ||
                measurement.resolved_upper != null) && (
                <Typography
                  variant="caption"
                  sx={{ color: "text.secondary", display: "block" }}
                  noWrap
                >
                  limits {measurement.resolved_lower ?? "—"}–
                  {measurement.resolved_upper ?? "—"} {measurement.unit || "mm"}
                </Typography>
              )}
              {measurement.ovality_measured != null && (
                <Typography
                  variant="caption"
                  sx={{
                    display: "block",
                    color:
                      measurement.max_ovality != null &&
                      measurement.ovality_measured > measurement.max_ovality
                        ? theme.palette.error.main
                        : "text.secondary",
                  }}
                  noWrap
                >
                  ovality {measurement.ovality_measured.toFixed(2)}{" "}
                  {measurement.unit || "mm"}
                  {measurement.max_ovality != null && ` (max ${measurement.max_ovality})`}
                </Typography>
              )}
            </>
          )}

          {!hasResult && (
            <Typography variant="body2" sx={{ color: "text.secondary" }}>
              Awaiting first result
            </Typography>
          )}
        </Box>

        <Box
          sx={{
            px: 3,
            py: 1.25,
            borderRadius: 1.5,
            minWidth: 88,
            textAlign: "center",
            fontWeight: 800,
            fontSize: "1.1rem",
            letterSpacing: "0.04em",
            color: hasResult ? "#fff" : "text.secondary",
            bgcolor: hasResult ? (passed ? "success.main" : "error.main") : "action.hover",
          }}
        >
          {hasResult ? (passed ? "OK" : "NOK") : "—"}
        </Box>
      </Box>
    </Paper>
  );
};

export default CameraPlaceholder;