import { useEffect, useMemo, useState } from "react";
import {
  defaultServerConnectionConfig,
  type ServerConnectionConfig,
  type ServerConnectionSyncResult,
  type ServerConnectionTestResult,
  type ServerSnapshotResult,
} from "../types";
import {
  backupVaultSnapshot,
  getServerConfigPath,
  loadServerConfig,
  saveServerConfig,
  syncServerNow,
  testServerConnection,
} from "../bridge/server";

interface Props {
  selectedProjectId: string | null;
  vaultRoot: string | null;
}

export function ServerConnectionPanel({ selectedProjectId, vaultRoot }: Props) {
  const [config, setConfig] = useState<ServerConnectionConfig>(defaultServerConnectionConfig());
  const [configPath, setConfigPath] = useState<string>("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [testResult, setTestResult] = useState<ServerConnectionTestResult | null>(null);
  const [syncResult, setSyncResult] = useState<ServerConnectionSyncResult | null>(null);
  const [snapshotResult, setSnapshotResult] = useState<ServerSnapshotResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getServerConfigPath()
      .then(setConfigPath)
      .catch(() => {});
    loadServerConfig()
      .then((loadedConfig) => {
        if (loadedConfig) {
          setConfig((current) => ({ ...current, ...loadedConfig }));
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    if (!selectedProjectId && !config.project_key) {
      return;
    }
    if (selectedProjectId && !config.project_key) {
      setConfig((current) => ({ ...current, project_key: selectedProjectId }));
    }
  }, [config.project_key, selectedProjectId]);

  const canTest = useMemo(() => {
    return Boolean(config.base_url.trim() && config.health_path.trim());
  }, [config.base_url, config.health_path]);

  const update = (patch: Partial<ServerConnectionConfig>) => {
    setConfig((current) => ({ ...current, ...patch }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setStatus("Saving server connection...");
    try {
      await saveServerConfig(normalizeConfig(config));
      setStatus("Server connection saved.");
    } catch (e) {
      setError(String(e));
      setStatus("Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    const next = defaultServerConnectionConfig();
    if (selectedProjectId) {
      next.project_key = selectedProjectId;
    }
    setConfig(next);
    setStatus("Reset to defaults.");
    setError(null);
    setTestResult(null);
    setSyncResult(null);
    setSnapshotResult(null);
  };

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    setStatus("Testing server connection...");
    try {
      const result = await testServerConnection(normalizeConfig(config));
      setTestResult(result);
      setStatus(result.ok ? "Connection looks good." : "Connection test failed.");
      if (!result.ok) {
        setError(result.message);
      }
    } catch (e) {
      setTestResult(null);
      setError(String(e));
      setStatus("Connection test failed.");
    } finally {
      setTesting(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    setStatus("Syncing server connection...");
    try {
      const result = await syncServerNow(normalizeConfig(config));
      setSyncResult(result);
      setStatus(result.ok ? "Server sync succeeded." : "Server sync failed.");
      if (!result.ok) {
        setError(result.message);
      }
    } catch (e) {
      setSyncResult(null);
      setError(String(e));
      setStatus("Server sync failed.");
    } finally {
      setSyncing(false);
    }
  };

  const handleSnapshot = async () => {
    if (!vaultRoot) {
      setError("Select a project vault before creating a snapshot.");
      return;
    }
    setSyncing(true);
    setError(null);
    setStatus("Uploading vault snapshot...");
    try {
      const result = await backupVaultSnapshot(normalizeConfig(config), vaultRoot);
      setSnapshotResult(result);
      setStatus(result.ok ? "Vault snapshot uploaded." : "Vault snapshot failed.");
      if (!result.ok) {
        setError(result.message);
      }
    } catch (e) {
      setSnapshotResult(null);
      setError(String(e));
      setStatus("Vault snapshot failed.");
    } finally {
      setSyncing(false);
    }
  };

  if (!loaded) {
    return <div className="panel">Loading server settings...</div>;
  }

  return (
    <div className="panel server-panel">
      <div className="server-panel__header">
        <div>
          <h3 className="panel__title">Server</h3>
          <div className="server-panel__subtitle">
            Configure your private workbench service. The connection file stays local and the auth token is stored in the OS keychain. Use vault snapshot backup for server-side mirroring; keep the local vault authoritative.
          </div>
        </div>
        {configPath && <div className="server-panel__path mono-sm">{configPath}</div>}
      </div>

      {error && <div className="server-panel__error">{error}</div>}
      {status && <div className="server-panel__status">{status}</div>}

      <div className="server-form">
        <label className="server-field server-field--toggle">
          <input
            type="checkbox"
            checked={config.enabled}
            onChange={(e) => update({ enabled: e.target.checked })}
          />
          <span>Enable server sync</span>
        </label>

        <label className="server-field">
          <span className="form-label">Profile name</span>
          <input
            className="form-input"
            value={config.profile_name}
            onChange={(e) => update({ profile_name: e.target.value })}
            placeholder="local-server"
          />
        </label>

        <label className="server-field">
          <span className="form-label">Base URL</span>
          <input
            className="form-input"
            value={config.base_url}
            onChange={(e) => update({ base_url: e.target.value })}
            placeholder="https://workbench.example.com"
          />
        </label>

        <label className="server-field">
          <span className="form-label">Project key</span>
          <input
            className="form-input"
            value={config.project_key}
            onChange={(e) => update({ project_key: e.target.value })}
            placeholder={selectedProjectId ?? "ahamkara"}
          />
        </label>

        <label className="server-field">
          <span className="form-label">Auth header</span>
          <input
            className="form-input"
            value={config.auth_header}
            onChange={(e) => update({ auth_header: e.target.value })}
            placeholder="Authorization"
          />
        </label>

        <label className="server-field">
          <span className="form-label">Auth token</span>
          <input
            className="form-input"
            type="password"
            value={config.auth_token}
            onChange={(e) => update({ auth_token: e.target.value })}
            placeholder="Stored locally on this machine"
          />
        </label>

        <label className="server-field">
          <span className="form-label">Health path</span>
          <input
            className="form-input"
            value={config.health_path}
            onChange={(e) => update({ health_path: e.target.value })}
            placeholder="/health"
          />
        </label>

        <label className="server-field">
          <span className="form-label">Events path</span>
          <input
            className="form-input"
            value={config.events_path}
            onChange={(e) => update({ events_path: e.target.value })}
            placeholder="/events"
          />
        </label>

        <label className="server-field">
          <span className="form-label">Snapshots path</span>
          <input
            className="form-input"
            value={config.snapshots_path}
            onChange={(e) => update({ snapshots_path: e.target.value })}
            placeholder="/snapshots"
          />
        </label>

        <label className="server-field">
          <span className="form-label">Sync interval (seconds)</span>
          <input
            className="form-input"
            type="number"
            min="5"
            step="1"
            value={config.sync_interval_seconds}
            onChange={(e) =>
              update({ sync_interval_seconds: Math.max(5, parseInt(e.target.value, 10) || 15) })
            }
          />
        </label>
      </div>

      <div className="server-actions">
        <button className="btn" onClick={handleReset} disabled={saving || testing}>
          Reset
        </button>
        <button
          className="btn"
          onClick={handleTest}
          disabled={testing || syncing || saving || !canTest}
        >
          {testing ? "Testing..." : "Test Connection"}
        </button>
        <button
          className="btn"
          onClick={handleSync}
          disabled={syncing || testing || saving || !canTest}
        >
          {syncing ? "Syncing..." : "Sync Now"}
        </button>
        <button
          className="btn"
          onClick={handleSnapshot}
          disabled={syncing || testing || saving || !canTest || !vaultRoot}
        >
          {syncing ? "Uploading..." : "Backup Snapshot"}
        </button>
        <button
          className="btn btn--primary"
          onClick={handleSave}
          disabled={saving || testing || syncing}
        >
          {saving ? "Saving..." : "Save Connection"}
        </button>
      </div>

      {testResult && (
        <div className={`server-result ${testResult.ok ? "server-result--ok" : "server-result--bad"}`}>
          <div className="server-result__line">
            <span className="server-result__label">Tested URL</span>
            <span className="mono-sm">{testResult.tested_url}</span>
          </div>
          <div className="server-result__line">
            <span className="server-result__label">Status</span>
            <span>{testResult.status_code ?? "n/a"}</span>
          </div>
          <div className="server-result__message">{testResult.message}</div>
        </div>
      )}

      {syncResult && (
        <div className={`server-result ${syncResult.ok ? "server-result--ok" : "server-result--bad"}`}>
          <div className="server-result__line">
            <span className="server-result__label">Event ID</span>
            <span className="mono-sm">{syncResult.event_id}</span>
          </div>
          <div className="server-result__line">
            <span className="server-result__label">Health</span>
            <span>{syncResult.health_status_code ?? "n/a"}</span>
          </div>
          <div className="server-result__line">
            <span className="server-result__label">Events</span>
            <span>{syncResult.events_status_code ?? "n/a"}</span>
          </div>
          <div className="server-result__message">{syncResult.message}</div>
          {syncResult.response_excerpt && (
            <div className="server-result__excerpt mono-sm">{syncResult.response_excerpt}</div>
          )}
        </div>
      )}

      {snapshotResult && (
        <div className={`server-result ${snapshotResult.ok ? "server-result--ok" : "server-result--bad"}`}>
          <div className="server-result__line">
            <span className="server-result__label">Snapshot</span>
            <span className="mono-sm">{snapshotResult.snapshot_id}</span>
          </div>
          <div className="server-result__line">
            <span className="server-result__label">Files</span>
            <span>{snapshotResult.file_count}</span>
          </div>
          <div className="server-result__line">
            <span className="server-result__label">HTTP</span>
            <span>{snapshotResult.status_code ?? "n/a"}</span>
          </div>
          <div className="server-result__message">{snapshotResult.message}</div>
          {snapshotResult.response_excerpt && (
            <div className="server-result__excerpt mono-sm">{snapshotResult.response_excerpt}</div>
          )}
        </div>
      )}
    </div>
  );
}

function normalizeConfig(config: ServerConnectionConfig): ServerConnectionConfig {
  return {
    ...config,
    profile_name: config.profile_name.trim(),
    base_url: config.base_url.trim().replace(/\/+$/, ""),
    project_key: config.project_key.trim(),
    auth_header: config.auth_header.trim() || "Authorization",
    auth_token: config.auth_token.trim(),
    health_path: normalizePath(config.health_path),
    events_path: normalizePath(config.events_path),
    snapshots_path: normalizePath(config.snapshots_path),
    sync_interval_seconds: Math.max(5, Number.isFinite(config.sync_interval_seconds) ? config.sync_interval_seconds : 15),
  };
}

function normalizePath(path: string) {
  const trimmed = path.trim();
  if (!trimmed) return "/";
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}
