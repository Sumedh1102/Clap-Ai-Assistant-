import { useEffect, useState } from "react";
import type { SystemMetrics } from "../types";

/** Polls real system metrics from the backend while the page is visible. */
export function useSystemMetrics(intervalMs = 3000) {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer = 0;

    const load = async () => {
      if (!document.hidden) {
        try {
          const res = await fetch("/api/system", { cache: "no-store" });
          if (res.ok && !cancelled) setMetrics(await res.json());
        } catch {
          /* backend unreachable — the connection indicator covers this */
        }
      }
      if (!cancelled) timer = window.setTimeout(load, intervalMs);
    };
    load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [intervalMs]);

  return metrics;
}
