import { useState } from "react";
import type { CommandResult } from "../types";
import { runDriftScan, startWatcher, stopWatcher } from "../bridge/cli";
import { openPath } from "../bridge/system";

interface Props {
  projectId: string | null;
  vaultRoot: string | null;
  workbenchRoot: string;
  onRefreshQueue: () => void;
}

export function WorkbenchActions({
  projectId,
  vaultRoot,
  workbenchRoot,
  onRefreshQueue,
}: Props) {
  const [output, setOutput] = useState<CommandResult | null>(null);
  const [watcherActive, setWatcherActive] = useState(false);
  const [running, setRunning] = useState(false);
  const [watchInterval, setWatchInterval] = useState("5");

  const handleDriftScan = async () => {
    if (!projectId) return;
    setRunning(true);
    try {
      const r = await runDriftScan(projectId);
      setOutput(r);
    } catch (e) {
      setOutput({ stdout: "", stderr: String(e), exit_code: 1 });
    } finally {
      setRunning(false);
    }
  };

  const handleStartWatcher = async () => {
    if (!projectId) return;
    try {
      const interval = parseFloat(watchInterval) || 5.0;
      await startWatcher(projectId, interval);
      setWatcherActive(true);
    } catch (e) {
      setOutput({ stdout: "", stderr: String(e), exit_code: 1 });
    }
  };

  const handleStopWatcher = async () => {
    try {
      await stopWatcher();
      setWatcherActive(false);
    } catch (e) {
      setOutput({ stdout: "", stderr: String(e), exit_code: 1 });
    }
  };

  return (
    <div className="panel workbench-actions">
      <h3 className="panel__title">Actions</h3>
      <div className="action-grid">
        <button
          className="btn"
          onClick={handleDriftScan}
          disabled={!projectId || running}
        >
          Drift Scan
        </button>
        <div className="action-group">
          <button
            className="btn"
            onClick={watcherActive ? handleStopWatcher : handleStartWatcher}
            disabled={!projectId}
          >
            {watcherActive ? "Stop Watcher" : "Start Watcher"}
          </button>
          {!watcherActive && (
            <input
              className="form-input form-input--narrow"
              type="number"
              min="1"
              step="1"
              value={watchInterval}
              onChange={(e) => setWatchInterval(e.target.value)}
              title="Poll interval (seconds)"
              disabled={!projectId}
            />
          )}
        </div>
        <button className="btn" onClick={onRefreshQueue}>
          Refresh Queue
        </button>
        <button
          className="btn"
          onClick={() => vaultRoot && openPath(vaultRoot)}
          disabled={!vaultRoot}
        >
          Open Project Vault
        </button>
        <button className="btn" onClick={() => openPath(workbenchRoot)}>
          Open Shared Vault
        </button>
      </div>
      {output && (
        <div className="command-result">
          {output.stdout && (
            <pre className="command-result__stdout">{output.stdout}</pre>
          )}
          {output.stderr && (
            <pre className="command-result__stderr">{output.stderr}</pre>
          )}
        </div>
      )}
    </div>
  );
}
