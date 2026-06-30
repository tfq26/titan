import type { RoutingConfig, EnvVarStatus, ProjectConfig } from "../types";
import { ModelPolicy } from "./ModelPolicy";
import { ServerConnectionPanel } from "./ServerConnectionPanel";

interface Props {
  routing: RoutingConfig | null;
  envStatus: EnvVarStatus[];
  projectConfig: ProjectConfig | null;
  selectedProjectId: string | null;
  vaultRoot: string | null;
  onRefreshRouting: () => void;
  onRefreshProjectConfig: () => void;
}

export function ConfigurePanel({
  routing,
  envStatus,
  projectConfig,
  selectedProjectId,
  vaultRoot,
  onRefreshRouting,
  onRefreshProjectConfig,
}: Props) {
  return (
    <div className="configure-tab">
      <div className="configure-tab__header">
        <h2 className="configure-tab__title">Configure</h2>
        <div className="configure-tab__subtitle">
          Manage models, roles, permissions, and server connection settings
        </div>
      </div>
      <ModelPolicy
        routing={routing}
        envStatus={envStatus}
        projectConfig={projectConfig}
        selectedProjectId={selectedProjectId}
        onRefreshRouting={onRefreshRouting}
        onRefreshProjectConfig={onRefreshProjectConfig}
      />
      {selectedProjectId && vaultRoot && (
        <ServerConnectionPanel
          selectedProjectId={selectedProjectId}
          vaultRoot={vaultRoot}
        />
      )}
    </div>
  );
}
