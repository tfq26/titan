import { useState, useCallback, useEffect } from "react";
import type { RoutingConfig, EnvVarStatus } from "../types";
import { readRouting } from "../bridge/files";
import { checkEnvVars } from "../bridge/system";

export function useRouting() {
  const [routing, setRouting] = useState<RoutingConfig | null>(null);
  const [envStatus, setEnvStatus] = useState<EnvVarStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await readRouting();
      setRouting(r);
      const allVars = new Set<string>();
      for (const m of r.models) {
        for (const v of m.env_vars) allVars.add(v);
      }
      const status = await checkEnvVars(Array.from(allVars));
      setEnvStatus(status);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return { routing, envStatus, error, refresh: load };
}
