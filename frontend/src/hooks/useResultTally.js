import { useEffect, useRef, useState } from "react";

// Presentation-only tally of results that have streamed past SINCE THIS PAGE
// OPENED. Deliberately NOT a verdict source: every OK/NOK total the operator
// acts on still comes from the backend's RingState (ok_total / nok_total).
// This exists solely to fill the per-defect and per-station breakdown the
// backend does not currently expose -- swap it for a real endpoint when one
// exists, and delete this file.
//
// Counts once per (camera, part_id): `results` holds the LATEST result per
// camera and re-renders on every frame, so without the seen-ref the same
// part would be counted repeatedly.
export default function useResultTally(results) {
  const seen = useRef({}); // camera_id -> last counted part_id
  const [tally, setTally] = useState({
    perCamera: {},                    // { camera_id: { ok, nok } }
    defects: {},                      // { defect_label: count }
    measurement: { ok: 0, nok: 0 },
  });

  useEffect(() => {
    let changed = false;
    const next = {
      perCamera: { ...tally.perCamera },
      defects: { ...tally.defects },
      measurement: { ...tally.measurement },
    };

    Object.entries(results || {}).forEach(([camId, r]) => {
      if (!r || r.part_id == null) return;
      if (seen.current[camId] === r.part_id) return;
      seen.current[camId] = r.part_id;
      changed = true;

      const cam = { ...(next.perCamera[camId] || { ok: 0, nok: 0 }) };
      if (r.passed) cam.ok += 1;
      else cam.nok += 1;
      next.perCamera[camId] = cam;

      if (r.defect_label) {
        next.defects[r.defect_label] =
          (next.defects[r.defect_label] || 0) + (r.defect_count || 1);
      }

      const m = r.measurement_data?.diameter_mm;
      if (m) {
        if (m.passed) next.measurement.ok += 1;
        else next.measurement.nok += 1;
      }
    });

    if (changed) setTally(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results]);

  return tally;
}