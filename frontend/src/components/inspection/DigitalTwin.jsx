import { useRef } from "react";
import { Box, Chip, Paper, Typography } from "@mui/material";

// Matches docs/reference/segment_slot_simulator.html exactly (per-station
// radial-band model, confirmed final -- replaces the earlier whole-slot
// single-color and worst-severity attempts from earlier today). Dark
// instrumentation-panel look, not this app's default light card -- a
// deliberate, scoped exception (CLAUDE.md Section 13): this app already has
// exactly this precedent (CameraPlaceholder.jsx's dark camera tiles, live
// equipment feeds against an otherwise light page).
//
// Model: each occupied slot is divided into N radial bands, one per
// INSPECTION station only (entry/reject/exit don't get a band -- they're
// transition points, not per-station verdicts). Band count/order comes
// from `stations` filtered to type==="inspection", in config order --
// never hardcoded. Each band's color reflects THAT station's own
// independent state for the current occupant:
//   unreached (part hasn't physically reached that station yet) -> gray
//   pending (reached it, camera fired, inference result not back) -> yellow
//   ok (that station passed) -> green
//   nok (that station failed) -> that station's own assigned color
// If every inspection station is ok, the slot collapses to one solid green
// wedge (matches the reference's allOk() shortcut) rather than N green
// bands -- once resolved-all-ok there's nothing left to distinguish.
//
// Slot state is read directly from the backend's per-tick RingState
// broadcast (ringState prop, MessageType.RingState -- see
// IndexerSlotTracker.station_states / app/utils/zeromq.publish_ring_state).
// No client-side reconstruction: no event-grouping heuristic, no per-camera
// accumulation -- the backend's data is the single source of truth this
// component renders, unconditionally.
const SIZE = 300;
const CENTER = SIZE / 2;
const R_STATION_LABEL = 138;
const R_STATION_MARK = 122;
const R_SLOT_OUTER = 112;
const R_SLOT_INNER = 78;

// Explicit dark-panel palette (not theme.palette, which is this app's LIGHT
// tokens -- wrong direction for a deliberately dark widget). OK=green/
// NOK=red per explicit operator instruction (2026-09-07) -- overrides an
// earlier blue/red choice that was picked purely for colorblind-safety
// margin; green/red/yellow is the deliberate call here, matching standard
// factory-floor HMI convention. Every state also carries a text label in
// the legend/tooltips as the CVD skill's required secondary encoding.
const PANEL_BG = "#11161d";
const PANEL_BORDER = "#262d38";
const TEXT_PRIMARY = "#E6EDF3";
const TEXT_SECONDARY = "#7D8590";
// EMPTY and BLANK render identically (BLANK is a sim-only backend concept --
// a permanently unfed slot for the verification harness -- with no distinct
// operator-facing color; both just read as "nothing here"). UNREACHED is
// visually far apart from IDLE_SLOT on purpose (light fuchsia vs. a
// clearly-visible mid-gray) so "no part" and "part present, hasn't gotten to
// this station yet" don't get confused -- per operator request 2026-09-07.
const IDLE_SLOT = "#96a7db"; // EMPTY (and BLANK) -- light fuchsia (plum)
const UNREACHED_COLOR = "#6E7B8F"; // a station this part hasn't physically reached yet -- clearly visible
const PENDING_COLOR = "#E8C547"; // reached the station, awaiting inference -- yellow
const OK_COLOR = "#3FB950"; // a station (or the whole slot, once all are ok) -- green
const FAIL_COLOR = "#F85149"; // generic NOK fallback (compact strip summary only)
const STATION_MARK = "#C9D1D9";
const EXIT_MARK = "#3FB950";
const REJECT_MARK = "#D29922"; // amber -- r1
const ENTRY_MARK = "#8B949E";
const MONO_FONT = "ui-monospace, 'SF Mono', Menlo, monospace";

// Per-station NOK coloring: each inspection station's own failure color, so
// a slot that failed at two stations shows two distinct band colors rather
// than one generic "NOK" red that can't tell you which station(s) failed.
// Fixed palette, cycled by station config order (not hue math) so a given
// station's color is stable and never lands in the OK/pending range.
// Generalizes to N inspection stations by cycling.
const NOK_COLOR_PALETTE = ["#A371F7", "#F85149", "#F0883E", "#DB61A2", "#79C0FF"];

function buildNokColorMap(inspectionStations) {
  const map = {};
  inspectionStations.forEach((s, i) => {
    map[s.station_id] = NOK_COLOR_PALETTE[i % NOK_COLOR_PALETTE.length];
  });
  return map;
}

const angleFor = (index, count) => (index / count) * 2 * Math.PI - Math.PI / 2;
const pointAt = (angle, radius) => ({ x: CENTER + radius * Math.cos(angle), y: CENTER + radius * Math.sin(angle) });

const stationMarkerColor = (station) => {
  if (station.type === "entry") return ENTRY_MARK;
  if (station.type === "exit") return EXIT_MARK;
  if (station.type === "reject") return REJECT_MARK;
  return STATION_MARK;
};

// One inspection station's band color, given its own unreached/pending/
// ok/nok state for the current occupant.
function bandColor(state, stationId, nokColorMap) {
  if (state === "pending") return PENDING_COLOR;
  if (state === "ok") return OK_COLOR;
  if (state === "nok") return nokColorMap[stationId] || FAIL_COLOR;
  return UNREACHED_COLOR; // "unreached" or missing
}

// Compact-strip summary color for a slot -- 10px is too small to show N
// bands legibly, so this collapses to one color by priority: any nok found
// anywhere wins (matches r1's "any nok is actionable" rule), else any
// pending, else all-ok green, else still-unreached gray.
function summaryColor(status, stationStates, inspectionStations) {
  if (status === "EMPTY" || status === "BLANK") return IDLE_SLOT;
  const states = inspectionStations.map((s) => stationStates[s.station_id] || "unreached");
  if (states.includes("nok")) return FAIL_COLOR;
  if (states.includes("pending")) return PENDING_COLOR;
  if (states.length > 0 && states.every((s) => s === "ok")) return OK_COLOR;
  return UNREACHED_COLOR;
}

const DigitalTwin = ({ nSlots, stations, ringState, revolutions, running }) => {
  // Monotonically-accumulated rotation, tracked via entry_slot_id's deltas
  // (wraparound handled explicitly) rather than the raw (entrySlotId/nSlots)
  // * 360 value, which resets to ~0 every revolution -- with the CSS
  // transition below, that reset made the ring visibly spin BACKWARDS
  // through ~360deg for an instant at every wraparound (a real animation
  // bug: the whole ring's visual position swung wildly, which reads as
  // "colors changing" since color is tied to position). This ref is purely
  // a presentation-layer animation concern -- it doesn't reconstruct any
  // backend state/verdict, unlike the client-side heuristics removed
  // earlier today.
  const rotationRef = useRef({ lastEntrySlotId: null, cumulativeSlots: 0 });
  if (nSlots && ringState) {
    const entrySlotId = ringState.entry_slot_id;
    const prev = rotationRef.current;
    if (prev.lastEntrySlotId === null) {
      prev.cumulativeSlots = entrySlotId;
    } else if (entrySlotId !== prev.lastEntrySlotId) {
      const delta = entrySlotId - prev.lastEntrySlotId;
      prev.cumulativeSlots += delta < 0 ? delta + nSlots : delta;
    }
    prev.lastEntrySlotId = entrySlotId;
  }

  if (!nSlots) return null;

  const inspectionStations = stations.filter((s) => s.type === "inspection");
  const nokColorMap = buildNokColorMap(inspectionStations);
  const bandWidth = (R_SLOT_OUTER - R_SLOT_INNER) / Math.max(inspectionStations.length, 1);
  const barWidth = Math.max(2, (2 * Math.PI * R_SLOT_INNER) / Math.max(nSlots, 1) - 2);

  const slotStatuses = new Array(nSlots).fill("EMPTY").map((fallback, i) => ringState?.slots?.[String(i)]?.status || fallback);
  const slotStationStates = new Array(nSlots).fill(null).map((_, i) => ringState?.slots?.[String(i)]?.station_states || {});
  const entrySlotId = ringState ? ringState.entry_slot_id : 0;
  const rotationDeg = (rotationRef.current.cumulativeSlots / nSlots) * 360; // monotonic -- never wraps, so the CSS transition never spins backward
  const inFlight = slotStatuses.filter((s) => s === "LOADED").length;

  // Entry isn't a real configured station (machine_config.yaml has no
  // "entry" entry) -- slot 0 is where a part enters by definition of the
  // ring-math itself (IndexerSlotTracker's entry_slot_id), so it's added
  // here purely for the twin's own legibility, positioned right where Exit
  // hands off back to it going clockwise (Entry -> s1 -> s2 -> r1 -> Exit -> Entry).
  const displayStations = [{ station_id: "Entry", type: "entry", slot_offset: 0 }, ...stations];

  return (
    <Paper
      sx={{
        p: 2,
        borderRadius: "10px",
        display: "flex",
        flexDirection: "column",
        gap: 1.25,
        height: "100%",
        overflow: "hidden",
        bgcolor: PANEL_BG,
        border: `1px solid ${PANEL_BORDER}`,
        color: TEXT_PRIMARY,
      }}
    >
      {/* Header: title + running pill */}
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography sx={{ fontWeight: 700, fontSize: "0.8rem", letterSpacing: "0.06em", color: TEXT_PRIMARY }}>
          INDEXER · {nSlots} SLOTS · {stations.length} STATIONS
        </Typography>
        <Chip
          size="small"
          label={running ? "RUNNING" : "STOPPED"}
          sx={{
            fontWeight: 700,
            fontSize: "0.6rem",
            letterSpacing: "0.04em",
            height: 20,
            bgcolor: running ? "rgba(63,185,80,0.18)" : "rgba(125,133,144,0.15)",
            color: running ? EXIT_MARK : TEXT_SECONDARY,
            border: `1px solid ${running ? "rgba(63,185,80,0.4)" : PANEL_BORDER}`,
          }}
        />
      </Box>

      {/* Stat readouts */}
      <Box sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
        <Stat label="SLOT AT ENTRY" value={entrySlotId} />
        <Stat label="REV" value={revolutions} />
        <Stat label="IN FLIGHT" value={inFlight} />
        <Stat label="OK" value={ringState ? ringState.ok_total : 0} />
        <Stat label="NOK" value={ringState ? ringState.nok_total : 0} />
      </Box>

      <Box sx={{ width: "100%", maxWidth: 300, mx: "auto" }}>
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} style={{ width: "100%", height: "auto" }}>
          {/* fixed station markers -- real slot_offset from /inspection/config, plus the synthetic Entry marker at slot 0 */}
          {displayStations.map((s) => {
            const angle = angleFor(s.slot_offset, nSlots);
            const mark = pointAt(angle, R_STATION_MARK);
            const label = pointAt(angle, R_STATION_LABEL);
            const color = stationMarkerColor(s);
            const disabled = s.type === "reject" && s.enabled === false;
            return (
              <g key={s.station_id} opacity={disabled ? 0.5 : 1}>
                <circle
                  cx={mark.x}
                  cy={mark.y}
                  r={2.5}
                  fill={disabled ? "none" : color}
                  stroke={disabled ? color : "none"}
                  strokeWidth={disabled ? 1 : 0}
                  strokeDasharray={disabled ? "1.5,1.5" : undefined}
                />
                <text x={label.x} y={label.y} fontSize={9} fontWeight={700} letterSpacing="0.03em" textAnchor="middle" fill={color}>
                  {s.station_id.toUpperCase()}
                  {disabled ? " (OFF)" : ""}
                </text>
                <text x={label.x} y={label.y + 10} fontSize={7} fontFamily={MONO_FONT} textAnchor="middle" fill={TEXT_SECONDARY}>
                  +{s.slot_offset}
                </text>
              </g>
            );
          })}

          {/* idle ring guide */}
          <circle cx={CENTER} cy={CENTER} r={(R_SLOT_INNER + R_SLOT_OUTER) / 2} fill="none" stroke={PANEL_BORDER} strokeWidth={R_SLOT_OUTER - R_SLOT_INNER + 4} opacity={0.35} />

          {/* rotating slot ring -- N per-station radial bands per occupied
              slot (band width = (R_OUT - R_IN) / inspection station count,
              never hardcoded), collapsing to one solid wedge for empty/
              blank/all-ok slots. */}
          <g style={{ transition: "transform .25s linear" }} transform={`rotate(${rotationDeg} ${CENTER} ${CENTER})`}>
            {slotStatuses.map((status, i) => {
              // Sign fix (found via video review, 2026-09-07): backend's
              // IndexerSlotTracker.station_slot_id() is (entry_slot_id -
              // offset) % n_slots -- a station's occupant is BEHIND entry
              // by its offset. Station markers above are placed at
              // angleFor(+offset, n) (clockwise). Combined with
              // rotationDeg growing positively with entry_slot_id, wedges
              // built from angleFor(+i, n) landed at (-entry_slot_id) %
              // n_slots under the Entry marker instead of entry_slot_id
              // itself -- confirmed against a recording where the stat
              // box read entry=7 but wedge 13 (== -7 mod 20) sat at Entry.
              // angleFor(-i, n) makes wedge i's screen position solve
              // correctly for every station simultaneously (verified: for
              // i = entry_slot_id - offset, the resulting screen angle
              // equals angleFor(offset, n) exactly, for any offset).
              const angle = angleFor(-i, nSlots);
              // Debug aid (per operator request 2026-09-07): the physical
              // slot index, black, at each wedge's mid-radius so it's
              // possible to correlate what's visually happening (e.g.
              // "slot 3 just filled") against a video recording. Sits
              // inside the same rotating <g> as the wedges so it stays
              // anchored to its own slot as the ring spins -- text itself
              // isn't counter-rotated (would need a second transform around
              // the global center), so at some ring angles it reads
              // sideways/upside-down; position, not orientation, is what
              // matters here.
              const labelPoint = pointAt(angle, (R_SLOT_INNER + R_SLOT_OUTER) / 2);
              const slotLabel = (
                <text
                  key={`label-${i}`}
                  x={labelPoint.x}
                  y={labelPoint.y}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontSize={7}
                  fontWeight={700}
                  fontFamily={MONO_FONT}
                  fill="#000000"
                >
                  {i}
                </text>
              );

              if (status !== "LOADED") {
                const inner = pointAt(angle, R_SLOT_INNER);
                const outer = pointAt(angle, R_SLOT_OUTER);
                return (
                  <g key={i}>
                    <line
                      x1={inner.x}
                      y1={inner.y}
                      x2={outer.x}
                      y2={outer.y}
                      stroke={IDLE_SLOT}
                      strokeWidth={barWidth}
                      strokeLinecap="butt"
                    />
                    {slotLabel}
                  </g>
                );
              }

              const states = slotStationStates[i];
              const allOk = inspectionStations.length > 0 && inspectionStations.every((s) => states[s.station_id] === "ok");

              if (allOk) {
                const inner = pointAt(angle, R_SLOT_INNER);
                const outer = pointAt(angle, R_SLOT_OUTER);
                return (
                  <g key={i}>
                    <line x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y} stroke={OK_COLOR} strokeWidth={barWidth} strokeLinecap="butt" />
                    {slotLabel}
                  </g>
                );
              }

              return (
                <g key={i}>
                  {inspectionStations.map((s, bandIdx) => {
                    const rOut = R_SLOT_OUTER - bandIdx * bandWidth;
                    const rIn = rOut - bandWidth;
                    const p1 = pointAt(angle, rIn);
                    const p2 = pointAt(angle, rOut);
                    const color = bandColor(states[s.station_id], s.station_id, nokColorMap);
                    return <line key={s.station_id} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke={color} strokeWidth={barWidth} strokeLinecap="butt" />;
                  })}
                  {slotLabel}
                </g>
              );
            })}
          </g>

          {/* center: revolution counter */}
          <text x={CENTER} y={CENTER - 4} textAnchor="middle" fontSize={26} fontWeight={700} fontFamily={MONO_FONT} fill={TEXT_PRIMARY}>
            {revolutions}
          </text>
          <text x={CENTER} y={CENTER + 15} textAnchor="middle" fontSize={9} letterSpacing="0.06em" fill={TEXT_SECONDARY}>
            REVOLUTIONS
          </text>
        </svg>
      </Box>

      {/* Compact slot-occupancy strip -- one summary color per slot (see
          summaryColor()); the sunburst ring above is where the full
          per-station band detail renders, 10px here is too small for that. */}
      <Box sx={{ display: "flex", gap: "2px", flexWrap: "wrap" }}>
        {slotStatuses.map((status, i) => {
          const states = slotStationStates[i];
          const color = summaryColor(status, states, inspectionStations);
          const detail = inspectionStations.map((s) => `${s.station_id}:${states[s.station_id] || "unreached"}`).join(" ");
          return (
            <Box
              key={i}
              sx={{ width: 10, height: 10, borderRadius: "2px", bgcolor: color }}
              title={`slot ${i} — ${status}${status === "LOADED" ? ` (${detail})` : ""}`}
            />
          );
        })}
      </Box>

      <Box sx={{ display: "flex", flexDirection: "column", gap: 0.4 }}>
        <LegendRow color={IDLE_SLOT} label="Empty" />
        <LegendRow color={UNREACHED_COLOR} label="Not yet reached that station" />
        <LegendRow color={PENDING_COLOR} label="Pending — awaiting inference" />
        <LegendRow color={OK_COLOR} label="Station passed" />
        {inspectionStations.map((s) => (
          <LegendRow key={s.station_id} color={nokColorMap[s.station_id]} label={`${s.station_id} failed`} />
        ))}
      </Box>
      <Typography variant="caption" sx={{ color: TEXT_SECONDARY, fontSize: "0.65rem", lineHeight: 1.4 }}>
        Live per-station ring state from IndexerSlotTracker (backend) — every
        band, OK/NOK total, and entry position is real, not a client-side proxy.
      </Typography>
    </Paper>
  );
};

const Stat = ({ label, value }) => (
  <Box sx={{ textAlign: "center" }}>
    <Typography sx={{ color: TEXT_SECONDARY, fontSize: "0.58rem", letterSpacing: "0.05em", display: "block" }}>{label}</Typography>
    <Typography sx={{ fontWeight: 700, fontFamily: MONO_FONT, fontSize: "0.95rem", color: TEXT_PRIMARY }}>{value}</Typography>
  </Box>
);

const LegendRow = ({ color, label }) => (
  <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
    <Box sx={{ width: 9, height: 9, borderRadius: "2px", bgcolor: color, flexShrink: 0 }} />
    <Typography sx={{ fontSize: "0.7rem", color: TEXT_SECONDARY }}>{label}</Typography>
  </Box>
);

export default DigitalTwin;
