import { useEffect, useMemo, useRef, useState } from "react";

// How many cells of at least (minW x minH) fit in the measured element, and
// what column count that implies.
//
// Measured, not assumed: the available height is whatever the flex cascade
// left over, which is knowable only after layout. A hardcoded capacity is
// wrong on every panel except the one it was tuned on.
export default function useGridCapacity(minW, minH, gap = 8) {
  const ref = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return useMemo(() => {
    // Always at least 1x1: a box briefly measuring 0 during mount must not
    // report a capacity of zero, or the pager divides by zero and the user
    // sees an empty station for a frame.
    const cols = Math.max(1, Math.floor((size.w + gap) / (minW + gap)));
    const rows = Math.max(1, Math.floor((size.h + gap) / (minH + gap)));
    return { ref, cols, rows, capacity: cols * rows };
  }, [size.w, size.h, minW, minH, gap]);
}