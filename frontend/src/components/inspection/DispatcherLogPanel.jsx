import { Box, Paper, Typography } from "@mui/material";

// Live, verbose ring-activity trail for commissioning/debugging -- mirrors
// the backend's own dispatcher.py log.info/.warning calls (home
// calibration, presence-sensor admits, station fires, reject arm/fire),
// each carrying the same home_relative_pulses the backend used to make its
// decision. Purely a debug aid: DigitalTwin/RingState stay the single
// source of truth for actual ring state, this panel never feeds back into
// it. Same dark instrumentation-panel look as DigitalTwin.jsx (CLAUDE.md
// Section 13's documented dark-widget exception).
const PANEL_BG = "#11161d";
const PANEL_BORDER = "#262d38";
const TEXT_PRIMARY = "#E6EDF3";
const TEXT_SECONDARY = "#7D8590";
const MONO_FONT = "ui-monospace, 'SF Mono', Menlo, monospace";

// One color per event type so a fast-scrolling trail is still scannable at
// a glance -- matches DigitalTwin's OK=green/NOK-adjacent=amber/red
// convention rather than inventing a new palette.
const EVENT_COLOR = {
  home_calibrated: "#58A6FF",
  part_admitted: "#96a7db",
  station_fired: "#E8C547",
  exit: "#3FB950",
  virtual_exit: "#3FB950",
  reject_armed: "#D29922",
  reject_fired: "#F85149",
};

const EVENT_LABEL = {
  home_calibrated: "HOME CALIBRATED",
  part_admitted: "PART ADMITTED",
  station_fired: "STATION FIRED",
  exit: "EXIT",
  virtual_exit: "VIRTUAL EXIT",
  reject_armed: "REJECT ARMED",
  reject_fired: "REJECT FIRED",
};

function formatTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString(undefined, { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

// Renders whichever pulse/slot/part fields a given event actually carries --
// the backend intentionally emits different field sets per event type (see
// zeromq.publish_dispatcher_event call sites in dispatcher.py), so this
// stays generic rather than hardcoding one shape.
function formatDetail(event) {
  const parts = [];
  if (event.station_id !== undefined) parts.push(`station=${event.station_id}`);
  if (event.slot_id !== undefined) parts.push(`slot=${event.slot_id}`);
  if (event.part_id !== undefined && event.part_id !== null) parts.push(`part=${event.part_id}`);
  if (event.raw_pulse !== undefined) parts.push(`raw_pulse=${event.raw_pulse}`);
  if (event.home_offset_pulses !== undefined) parts.push(`home_offset=${event.home_offset_pulses}`);
  if (event.pulse_count_at_detection !== undefined) parts.push(`detected_at=${event.pulse_count_at_detection}`);
  if (event.corrected_detection !== undefined) parts.push(`corrected=${event.corrected_detection}`);
  if (event.target_fire_pulse !== undefined) parts.push(`target=${event.target_fire_pulse}`);
  if (event.home_relative_pulses !== undefined) parts.push(`pulse=${event.home_relative_pulses}`);
  return parts.join("  ");
}

const DispatcherLogPanel = ({ events }) => {
  return (
    <Paper
      sx={{
        p: 1.25,
        borderRadius: "10px",
        display: "flex",
        flexDirection: "column",
        gap: 0.75,
        height: "100%",
        overflow: "hidden",
        bgcolor: PANEL_BG,
        border: `1px solid ${PANEL_BORDER}`,
        color: TEXT_PRIMARY,
      }}
    >
      <Typography sx={{ fontWeight: 700, fontSize: "0.75rem", letterSpacing: "0.06em", flexShrink: 0 }}>
        RING ACTIVITY LOG
      </Typography>
      <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 0.25 }}>
        {(!events || events.length === 0) && (
          <Typography sx={{ fontFamily: MONO_FONT, fontSize: "0.7rem", color: TEXT_SECONDARY }}>
            Waiting for ring activity…
          </Typography>
        )}
        {(events || []).map((event, i) => (
          <Box key={i} sx={{ display: "flex", gap: 0.75, alignItems: "baseline", fontFamily: MONO_FONT, fontSize: "0.68rem", lineHeight: 1.5 }}>
            <Box component="span" sx={{ color: TEXT_SECONDARY, flexShrink: 0 }}>
              {formatTime(event.ts)}
            </Box>
            <Box component="span" sx={{ color: EVENT_COLOR[event.event] || TEXT_PRIMARY, fontWeight: 700, flexShrink: 0 }}>
              {EVENT_LABEL[event.event] || event.event}
            </Box>
            <Box component="span" sx={{ color: TEXT_PRIMARY, overflowWrap: "anywhere" }}>
              {formatDetail(event)}
            </Box>
          </Box>
        ))}
      </Box>
    </Paper>
  );
};

export default DispatcherLogPanel;
