import { useState, useCallback } from "react";
import type { TaskDetail } from "../types";
import { readTask } from "../bridge/files";

export function useTaskDetail(vaultRoot: string | null) {
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTask = useCallback(
    async (path: string) => {
      if (!vaultRoot) return;
      setLoading(true);
      try {
        const t = await readTask(path, vaultRoot);
        setTask(t);
        setError(null);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    },
    [vaultRoot]
  );

  const clear = useCallback(() => {
    setTask(null);
    setError(null);
  }, []);

  return { task, loading, error, loadTask, clear };
}
