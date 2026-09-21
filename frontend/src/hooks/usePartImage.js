import { useEffect, useState } from "react";

import api from "../api/axios";

/**
 * Fetch a part's image through the axios instance and expose it as an
 * object URL.
 *
 * A plain <img src="/api/parts/12/image"> cannot work here: it resolves
 * against the frontend origin rather than the backend, misses the /v1
 * prefix, and carries no Authorization header — so the operator router
 * would reject it. Going through axios inherits all three.
 */
export default function usePartImage(partId, hasImage) {
  const [url, setUrl] = useState(null);

  useEffect(() => {
    if (!partId || !hasImage) {
      setUrl(null);
      return;
    }

    let objectUrl = null;
    let cancelled = false;

    api
      .get(`/parts/${partId}/image`, { responseType: "blob" })
      .then(({ data }) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(data);
        setUrl(objectUrl);
      })
      .catch(() => !cancelled && setUrl(null));

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [partId, hasImage]);

  return url;
}