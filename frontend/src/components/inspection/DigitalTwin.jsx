import { useEffect, useRef, useState } from "react";
import { Box, Chip, Paper, Typography } from "@mui/material";

// Matches a reference HMI-style digital-twin mockup the user provided
// (stat header, radial sunburst ring, station labels at their real
// offset, a compact slot strip) -- including its dark instrumentation-
// panel look, not this app's default light card. That's a deliberate,
// scoped exception, not a competing design system (CLAUDE.md Section 13):
// this app already has exactly this precedent -- CameraPlaceholder.jsx's
// camera tiles are dark (theme.palette.grey[900]) because they're live
// equipment feeds against an otherwise light page. The digital twin is
// the same category of thing (live equipment telemetry), styled the same
// deliberate way, not a random departure from theme.js.
//
// Per-station defect coloring: each inspection station gets its own fixed
// color (evenly spaced hues, N stations -> N colors, computed dynamically
// -- never hardcoded for 2 stations). A slot that failed at exactly one
// station renders that station's color; a slot that failed at multiple
// stations (e.g. s1 AND s2) renders BOTH colors as stacked segments on the
// same radial bar, rather than inventing a combinatorial palette (2^N
// combinations doesn't scale) -- this scales linearly with station count
// and stays visually decomposable at a glance.
//
// Honest caveat, unchanged from earlier versions: today's StationDispatcher
// fires all stations on the same simulation timer, not real PLC-pulse-
// driven transport (dispatcher.py's own docstring flags PLC-driven
// dispatch as not wired yet). To let the SAME simulated part accumulate
// results from multiple stations (needed for the multi-station-defect
// case above), this groups events arriving within ROUND_WINDOW_MS of each
// other into one "fire round" and advances the ring by one slot per
// round, then places each event using the station's REAL slot_offset --
// the same ring-math formula IndexerSlotTracker.station_offsets uses, not
// an approximation. Still a proxy (no real encoder pulses), but the
// slot/station geometry is real and internally consistent.
const SIZE = 300;
const CENTER = SIZE / 2;
const R_STATION_LABEL = 138;
const R_STATION_MARK = 122;
const R_SLOT_OUTER = 112;
const R_SLOT_INNER = 78;
const ROUND_WINDOW_MS = 800; // events within this window of each other = the same fire round
const ENTRY_INTERVAL_ROUNDS = 2; // a new part enters every Nth round -- leaves visible empty gaps

// Explicit dark-panel palette (not theme.palette, which is this app's
// LIGHT tokens -- wrong direction for a deliberately dark widget). Picked
// to match the reference mockup's own colors.
const PANEL_BG = "#11161d";
const PANEL_BORDER = "#262d38";
const TEXT_PRIMARY = "#E6EDF3";
const TEXT_SECONDARY = "#7D8590";
const IDLE_SLOT = "#232b36";
const OCCUPIED_PASS = "#58A6FF";
const STATION_MARK = "#C9D1D9";
const EXIT_MARK = "#3FB950";
const ENTRY_MARK = "#8B949E";
const MULTI_FAIL_RING = "#F85149";
const MONO_FONT = "ui-monospace, 'SF Mono', Menlo, monospace";

const angleFor = (index, count) => (index / count) * 2 * Math.PI - Math.PI / 2;
const pointAt = (angle, radius) => ({ x: CENTER + radius * Math.cos(angle), y: CENTER + radius * Math.sin(angle) });
const mod = (n, m) => ((n % m) + m) % m;

const stationMarkerColor = (station) => {
  if (station.kind === "entry") return ENTRY_MARK;
  if (station.station_id?.startsWith("exit")) return EXIT_MARK;
  return STATION_MARK;
};

// Offset away from hue 0 (pure red) -- that's already this panel's
// reserved error/multi-failure color, so station index 0 shouldn't land
// on it too. N inspection stations -> N evenly-spaced hues, dynamic --
// never hardcoded for a fixed station count. Deterministic order (array
// order = config order) so a given station keeps the same color always.
const HUE_OFFSET = 40;

function buildStationColorMap(inspectionStations) {
  const n = inspectionStations.length;
  const map = {};
  inspectionStations.forEach((s, i) => {
    const hue = Math.round((HUE_OFFSET + (360 * i) / Math.max(n, 1)) % 360);
    map[s.station_id] = `hsl(${hue}, 75%, 60%)`; // higher L than a light-theme pick -- needs to read against a dark panel
  });
  return map;
}

const DigitalTwin = ({ nSlots, stations, lastEvent, revolutions, running }) => {
  const [slots, setSlots] = useState([]); // null | { results: {station_id: passed}, enteredAtTick }
  const [rotationDeg, setRotationDeg] = useState(0);
  const [tick, setTick] = useState(0);
  const entryTickRef = useRef(0);
  const lastEventAtRef = useRef(0);

  const inspectionStations = stations.filter((s) => !s.station_id?.startsWith("exit"));
  const stationColorMap = buildStationColorMap(inspectionStations);
  const barWidth = Math.max(2, (2 * Math.PI * R_SLOT_INNER) / Math.max(nSlots, 1) - 2);

  // (Re)size the ring when the recipe's slot count becomes known/changes.
  useEffect(() => {
    setSlots(new Array(nSlots || 0).fill(null));
    entryTickRef.current = 0;
    lastEventAtRef.current = 0;
    setTick(0);
    setRotationDeg(0);
  }, [nSlots]);

  useEffect(() => {
    if (!lastEvent || !nSlots || stations.length === 0) return;

    const now = Date.now();
    const isNewRound = now - lastEventAtRef.current > ROUND_WINDOW_MS;
    lastEventAtRef.current = now;
    if (isNewRound) entryTickRef.current += 1;
    const entryTick = entryTickRef.current;

    const station = stations.find((s) => s.station_id === lastEvent.station_id);
    const offset = station ? station.slot_offset : 0;
    const stationSlot = mod(entryTick - offset, nSlots);
    const entrySlotNow = mod(entryTick, nSlots);
    const exitStation = stations.find((s) => s.station_id?.startsWith("exit"));

    setSlots((prev) => {
      const next = [...prev];

      if (isNewRound) {
        // Entry interval -- a real indexer disc isn't 100% full end to
        // end; a new part only enters every ENTRY_INTERVAL_ROUNDS rounds,
        // same as the reference file's entry_interval_ticks. Previously
        // this created a new part every single round with no gaps, which
        // filled the whole ring solid within about a minute -- that's
        // what "no empty slots" was.
        if (entryTick % ENTRY_INTERVAL_ROUNDS === 0 && !next[entrySlotNow]) {
          next[entrySlotNow] = { results: {}, enteredAtTick: entryTick };
        }
        // Clear whatever slot is now physically AT the exit station's
        // real offset -- it has left the ring, matching the reference
        // file's own step() (slots[slotIdx] = null right at exit).
        // Previously slots only cleared after an arbitrary full-
        // revolution timeout, which (a) was wrong -- a part leaves at
        // Exit's offset, not after a full lap -- and (b) never actually
        // fired in practice because of the bug fixed below, so nothing
        // was ever seen clearing at all.
        if (exitStation) {
          next[mod(entryTick - exitStation.slot_offset, nSlots)] = null;
        }
      }

      // Only attach a result to a slot that a real (interval-gated) entry
      // actually created -- previously this fabricated a phantom slot
      // via `next[stationSlot] || {...}` whenever nothing was there yet,
      // and that phantom's enteredAtTick kept resetting to "now" every
      // time it re-triggered, which meant the full-revolution clear
      // condition could never catch up. That's why nothing ever returned
      // to empty.
      const existing = next[stationSlot];
      if (existing) {
        next[stationSlot] = { ...existing, results: { ...existing.results, [lastEvent.station_id]: lastEvent.passed } };
      }

      return next;
    });

    setTick(entryTick);
    // Positive = clockwise in SVG (y-axis points down, so increasing
    // rotate() angle turns clockwise on screen).
    setRotationDeg((mod(entryTick, nSlots) / nSlots) * 360);
  }, [lastEvent, nSlots, stations]);

  if (!nSlots) return null;

  // Entry isn't a real configured station (machine_config.yaml has no
  // "entry" entry, only inspection stations + one exit) -- slot 0 is where
  // a part enters by definition of the ring-math itself
  // (IndexerSlotTracker's entry_slot_id), so it's added here purely for
  // the twin's own legibility, positioned right where Exit hands off back
  // to it going clockwise (Entry -> s1 -> s2 -> ... -> Exit -> Entry).
  const displayStations = [{ station_id: "Entry", kind: "entry", slot_offset: 0 }, ...stations];
  const inFlight = slots.filter(Boolean).length;
  const slotAtEntry = mod(tick, nSlots);

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
        <Stat label="ENCODER" value={tick} />
        <Stat label="SLOT AT ENTRY" value={slotAtEntry} />
        <Stat label="REV" value={revolutions} />
        <Stat label="IN FLIGHT" value={inFlight} />
      </Box>

      <Box sx={{ width: "100%", maxWidth: 300, mx: "auto" }}>
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} style={{ width: "100%", height: "auto" }}>
          {/* fixed station markers -- real slot_offset from /inspection/config, plus the synthetic Entry marker at slot 0 */}
          {displayStations.map((s) => {
            const angle = angleFor(s.slot_offset, nSlots);
            const mark = pointAt(angle, R_STATION_MARK);
            const label = pointAt(angle, R_STATION_LABEL);
            const color = stationMarkerColor(s);
            return (
              <g key={s.station_id}>
                <circle cx={mark.x} cy={mark.y} r={2.5} fill={color} />
                <text x={label.x} y={label.y} fontSize={9} fontWeight={700} letterSpacing="0.03em" textAnchor="middle" fill={color}>
                  {s.station_id.toUpperCase()}
                </text>
                <text x={label.x} y={label.y + 10} fontSize={7} fontFamily={MONO_FONT} textAnchor="middle" fill={TEXT_SECONDARY}>
                  +{s.slot_offset}
                </text>
              </g>
            );
          })}

          {/* idle ring guide */}
          <circle cx={CENTER} cy={CENTER} r={(R_SLOT_INNER + R_SLOT_OUTER) / 2} fill="none" stroke={PANEL_BORDER} strokeWidth={R_SLOT_OUTER - R_SLOT_INNER + 4} opacity={0.35} />

          {/* rotating slot ring -- sunburst radial bars, one per slot. A
              slot with failures at multiple stations renders as stacked
              segments, one per failing station's color. */}
          <g style={{ transition: "transform .25s linear" }} transform={`rotate(${rotationDeg} ${CENTER} ${CENTER})`}>
            {slots.map((slot, i) => {
              const angle = angleFor(i, nSlots);
              const failedStations = slot ? Object.entries(slot.results).filter(([, passed]) => !passed).map(([sid]) => sid) : [];

              if (!slot || failedStations.length === 0) {
                const inner = pointAt(angle, R_SLOT_INNER);
                const outer = pointAt(angle, R_SLOT_OUTER);
                const color = slot ? OCCUPIED_PASS : IDLE_SLOT;
                return (
                  <line key={i} x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y} stroke={color} strokeWidth={barWidth} strokeLinecap="butt" />
                );
              }

              return (
                <g key={i}>
                  {failedStations.map((sid, segIdx) => {
                    const segCount = failedStations.length;
                    const rStart = R_SLOT_INNER + ((R_SLOT_OUTER - R_SLOT_INNER) * segIdx) / segCount;
                    const rEnd = R_SLOT_INNER + ((R_SLOT_OUTER - R_SLOT_INNER) * (segIdx + 1)) / segCount;
                    const p1 = pointAt(angle, rStart);
                    const p2 = pointAt(angle, rEnd);
                    return (
                      <line key={sid} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke={stationColorMap[sid]} strokeWidth={barWidth} strokeLinecap="butt" />
                    );
                  })}
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

      {/* Compact slot-occupancy strip */}
      <Box sx={{ display: "flex", gap: "2px", flexWrap: "wrap" }}>
        {slots.map((slot, i) => {
          const failedStations = slot ? Object.entries(slot.results).filter(([, passed]) => !passed).map(([sid]) => sid) : [];
          const color = !slot ? IDLE_SLOT : failedStations.length ? stationColorMap[failedStations[0]] : OCCUPIED_PASS;
          return (
            <Box
              key={i}
              sx={{
                width: 10,
                height: 10,
                borderRadius: "2px",
                bgcolor: color,
                boxShadow: failedStations.length > 1 ? `0 0 0 1.5px ${MULTI_FAIL_RING} inset` : "none",
              }}
              title={`slot ${i}${failedStations.length ? ` — failed at ${failedStations.join(", ")}` : ""}`}
            />
          );
        })}
      </Box>

      <Box sx={{ display: "flex", flexDirection: "column", gap: 0.4 }}>
        <LegendRow color={IDLE_SLOT} label="Empty slot" />
        <LegendRow color={OCCUPIED_PASS} label="Occupied — passing" />
        {inspectionStations.map((s) => (
          <LegendRow key={s.station_id} color={stationColorMap[s.station_id]} label={`Failed at ${s.station_id}`} />
        ))}
      </Box>
      <Typography variant="caption" sx={{ color: TEXT_SECONDARY, fontSize: "0.65rem", lineHeight: 1.4 }}>
        Live proxy — real per-slot encoder tracking isn't wired into this
        simulation-timer build yet (ENCODER/SLOT AT ENTRY/IN FLIGHT above
        are derived the same way, not a real PLC read). Station positions
        and per-station colors are real.
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
