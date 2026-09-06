import { Box, Paper, Typography, useTheme } from "@mui/material";

// SVG slot-ring visualization. Renders once, above the station tabs, so it
// stays visible regardless of which page/tab is active (the "digital twin
// on all tabs" requirement -- it's page-independent chrome, not per-tab
// content).
//
// Honest caveat, shown in the caption: today's StationDispatcher fires
// stations on a simulation timer and never feeds a real per-slot occupancy
// state (dispatcher.py's own docstring flags PLC-driven dispatch as not
// wired yet) -- there's no real "which physical slot holds which part"
// truth to render yet. This draws a live *proxy*: the slot ring, real
// station positions (from /inspection/config's slot_offset, the same
// formula IndexerSlotTracker itself uses), and the most recent fire events
// colored by pass/fail with a short fading trail -- genuinely live, just
// not yet backed by real encoder-slot tracking.
const RING_RADIUS = 110;
const CENTER = 140;
const TRAIL_LENGTH = 6;

const stateColor = (theme, state) => {
  switch (state) {
    case "ok":
      return theme.palette.success.main;
    case "nok":
      return theme.palette.error.main;
    default:
      return theme.palette.grey[300];
  }
};

const DigitalTwin = ({ nSlots, stations, recentEvents, revolutions }) => {
  const theme = useTheme();
  if (!nSlots) return null;

  const angleForSlot = (slot) => (slot / nSlots) * 2 * Math.PI - Math.PI / 2;
  const pointOnRing = (angle, radius) => ({
    x: CENTER + radius * Math.cos(angle),
    y: CENTER + radius * Math.sin(angle),
  });

  // Most recent N events, newest last -- newest gets full opacity, older
  // ones fade out, giving the ring a live "trailing" feel.
  const trail = recentEvents.slice(-TRAIL_LENGTH);

  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: "10px", display: "flex", alignItems: "center", gap: 3, mb: 3 }}>
      <Box sx={{ position: "relative", width: CENTER * 2, height: CENTER * 2, flexShrink: 0 }}>
        <svg width={CENTER * 2} height={CENTER * 2} viewBox={`0 0 ${CENTER * 2} ${CENTER * 2}`}>
          {/* base ring */}
          <circle cx={CENTER} cy={CENTER} r={RING_RADIUS} fill="none" stroke={theme.palette.grey[200]} strokeWidth={2} />

          {/* slot ticks */}
          {Array.from({ length: nSlots }, (_, i) => {
            const { x, y } = pointOnRing(angleForSlot(i), RING_RADIUS);
            return <circle key={i} cx={x} cy={y} r={3} fill={theme.palette.grey[300]} />;
          })}

          {/* trailing recent fires */}
          {trail.map((ev, idx) => {
            const { x, y } = pointOnRing(angleForSlot(ev.slot % nSlots), RING_RADIUS);
            const opacity = 0.3 + (0.7 * (idx + 1)) / trail.length;
            return <circle key={ev.key} cx={x} cy={y} r={7} fill={stateColor(theme, ev.state)} opacity={opacity} />;
          })}

          {/* station markers, just outside the ring, at their real slot offset */}
          {stations.map((s) => {
            const angle = angleForSlot(s.slot_offset);
            const outer = pointOnRing(angle, RING_RADIUS + 14);
            const label = pointOnRing(angle, RING_RADIUS + 28);
            return (
              <g key={s.station_id}>
                <line
                  x1={pointOnRing(angle, RING_RADIUS).x}
                  y1={pointOnRing(angle, RING_RADIUS).y}
                  x2={outer.x}
                  y2={outer.y}
                  stroke={theme.palette.primary.main}
                  strokeWidth={2}
                />
                <text x={label.x} y={label.y} fontSize={11} fontWeight={700} textAnchor="middle" fill={theme.palette.text.primary}>
                  {s.station_id}
                </text>
              </g>
            );
          })}

          {/* center: revolution counter */}
          <text x={CENTER} y={CENTER - 4} textAnchor="middle" fontSize={26} fontWeight={700} fill={theme.palette.text.primary}>
            {revolutions}
          </text>
          <text x={CENTER} y={CENTER + 16} textAnchor="middle" fontSize={11} fill={theme.palette.text.secondary}>
            revolutions
          </text>
        </svg>
      </Box>

      <Box>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
          Digital Twin
        </Typography>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5 }}>
          <LegendRow color={theme.palette.grey[300]} label="Empty slot" />
          <LegendRow color={theme.palette.success.main} label="OK — exiting" />
          <LegendRow color={theme.palette.error.main} label="NOK — rejecting" />
        </Box>
        <Typography variant="caption" sx={{ display: "block", mt: 1.5, color: theme.palette.text.secondary, maxWidth: 220 }}>
          Live proxy view — real per-slot encoder tracking isn't wired into
          this simulation-timer build yet; station positions are real,
          slot occupancy is a recent-fires trail.
        </Typography>
      </Box>
    </Paper>
  );
};

const LegendRow = ({ color, label }) => (
  <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
    <Box sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: color }} />
    <Typography variant="caption">{label}</Typography>
  </Box>
);

export default DigitalTwin;
