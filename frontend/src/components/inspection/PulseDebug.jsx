import { Box, Paper, Typography } from "@mui/material";

// TEMP (2026-09-24): live view of every number the slot calculation uses,
// from the backend's RingState broadcast (ringState.debug, filled by
// StationDispatcher._pulse_debug_snapshot in real-PLC mode only). Added to
// diagnose "digital twin not rotating" on real hardware -- remove once the
// indexer is confirmed stable.
//
// How to read it: while the disc turns, RAW should climb (and wrap at CPR),
// ACCUMULATED and HOME-RELATIVE should climb with it, and ENTRY SLOT should
// step every PULSES/SLOT counts. BACKWARD STEPS counts readings lower than
// the previous one; while BELOW HIGH-WATER > 0, ACCUMULATED holds (no
// double counting) until RAW passes the high-water mark again. If HOME OFFSET stays
// "not homed", the part sensor never gave its first rising edge.

const PANEL_BG = "#11161d";
const PANEL_BORDER = "#262d38";
const TEXT_PRIMARY = "#E6EDF3";
const TEXT_SECONDARY = "#7D8590";
const WARN = "#E8C547";
const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

const fmt = (v) => (v === null || v === undefined ? "—" : String(v));

const ROWS = [
  ["raw_pulse", "RAW (encoder_indexer_ppr)"],
  ["high_water", "HIGH-WATER"],
  ["gap_last_tick", "GAP LAST TICK"],
  ["accumulated", "ACCUMULATED"],
  ["home_offset", "HOME OFFSET"],
  ["home_relative", "HOME-RELATIVE"],
  ["tracker_pulse", "TRACKER PULSE (0..CPR)"],
  ["pulses_per_slot", "PULSES / SLOT"],
  ["entry_slot_id", "ENTRY SLOT"],
  ["encoder_cpr", "CPR"],
  ["part_sensor", "PART SENSOR"],
  ["below_high_water", "BELOW HIGH-WATER"],
  ["backward_ticks", "BACKWARD STEPS"],
  ["backward_counts", "BACKWARD COUNTS"],
  ["last_back_by", "LAST BACK BY"],
  ["tick_ms", "TICK (ms)"],
  ["rpm", "RPM (measured)"],
  ["rev_peak_so_far", "REV PEAK SO FAR"],
  ["revolutions_checked", "REVS CHECKED"],
];

const PulseDebug = ({ debug }) => (
  <Paper
    elevation={0}
    sx={{ bgcolor: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 2, p: 1.5 }}
  >
    <Typography sx={{ fontWeight: 700, fontSize: "0.75rem", letterSpacing: "0.06em", color: TEXT_PRIMARY, mb: 1 }}>
      PULSE DEBUG (TEMP)
    </Typography>
    {!debug ? (
      <Typography sx={{ fontSize: "0.72rem", color: TEXT_SECONDARY }}>
        No pulse data — real-PLC mode only, and only while the dispatcher is running.
      </Typography>
    ) : (
      <Box component="dl" sx={{ m: 0, display: "grid", gridTemplateColumns: "1fr auto", rowGap: 0.25, columnGap: 1 }}>
        {ROWS.map(([key, label]) => {
          const value = key === "home_offset" && debug.home_offset == null ? "not homed" : fmt(debug[key]);
          const warn = (key === "home_offset" && debug.home_offset == null) || (key === "backward_ticks" && debug.backward_ticks > 0);
          return [
            <Typography key={`${key}-l`} component="dt" sx={{ fontSize: "0.68rem", color: TEXT_SECONDARY }}>
              {label}
            </Typography>,
            <Typography
              key={`${key}-v`}
              component="dd"
              sx={{ m: 0, fontSize: "0.72rem", fontFamily: MONO, textAlign: "right", color: warn ? WARN : TEXT_PRIMARY }}
            >
              {value}
            </Typography>,
          ];
        })}
      </Box>
    )}
  </Paper>
);

export default PulseDebug;
