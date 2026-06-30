import { useState, useCallback } from "react";
import type { QueueState } from "../types";
import { readQueue } from "../bridge/files";

const EMPTY: QueueState = {
  open: [],
  claimed: [],
  review_needed: [],
  completed: [],
  blocked: [],
};

export function useQueue(vaultRoot: string | null) {
  const [queue, setQueue] = useState<QueueState>(EMPTY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!vaultRoot) return;
    setLoading(true);
    try {
      const q = await readQueue(vaultRoot);
      setQueue(q);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [vaultRoot]);

  return { queue, loading, error, refresh };
}
