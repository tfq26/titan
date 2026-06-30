import { useState, useEffect } from "react";
import type { TraceConfig } from "../types";
import { getTraceConfig } from "../bridge/system";

interface Props {
  sessionId: string | null;
  projectId: string | null;
}

export function TracePanel({ sessionId, projectId }: Props) {
  const [config, setConfig] = useState<TraceConfig | null>(null);

  useEffect(() => {
    getTraceConfig().then(setConfig).catch(() => {});
  }, []);

  return (
    <div className="panel trace-panel">
      <h3 className="panel__title">Tracing</h3>
      {config ? (
        <div className="trace-fields">
          <div className="field">
            <span className="field__label">LangSmith Tracing</span>
            <span className={`field__value ${config.tracing_enabled ? "text--ok" : "text--muted"}`}>
              {config.tracing_enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          {config.project_name && (
            <div className="field">
              <span className="field__label">Project</span>
              <span className="field__value">{config.project_name}</span>
            </div>
          )}
          {projectId && (
            <div className="field">
              <span className="field__label">Workbench Project</span>
              <span className="field__value">{projectId}</span>
            </div>
          )}
          {sessionId && (
            <div className="field">
              <span className="field__label">Session ID</span>
              <span className="field__value mono-sm">{sessionId}</span>
            </div>
          )}
          {config.endpoint && (
            <div className="field">
              <span className="field__label">Endpoint</span>
              <span className="field__value mono-sm">{config.endpoint}</span>
            </div>
          )}
        </div>
      ) : (
        <div className="panel--empty">Loading trace config...</div>
      )}
    </div>
  );
}
