import { useEffect, useState } from "react";
import api from "../api/axios";

// Polls the persisted rollup. Deliberately NOT on the ZMQ stream: this is a
// summary of rows results_writer has written, so a few seconds of lag is
// correct -- the live per-camera detail is already on the stream.
//
// A 404 means "no session to analyse" (none running, or this part has no DB
// row so persistence is off -- see inspection_session._create_part_session).
// That is a normal state, not an error, so it clears to null quietly.
const POLL_MS = 3000;

export default function useSessionAnalysis(enabled = true) {
  const [analysis, setAnalysis] = useState(null);

  useEffect(() => {
    if (!enabled) {
      setAnalysis(null);
      return undefined;
    }
    let cancelled = false;

    const poll = () => {
      api
        .get("/inspection/session/analysis")
        .then(({ data }) => !cancelled && setAnalysis(data))
        .catch(() => !cancelled && setAnalysis(null));
    };

    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [enabled]);

  return analysis;
}