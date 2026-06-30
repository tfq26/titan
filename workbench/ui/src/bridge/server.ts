import { invoke } from "@tauri-apps/api/core";
import type {
  ServerConnectionConfig,
  ServerConnectionTestResult,
  ServerConnectionSyncResult,
  ServerSnapshotResult,
} from "../types";

export async function loadServerConfig(): Promise<ServerConnectionConfig | null> {
  return invoke("load_server_config");
}

export async function saveServerConfig(
  config: ServerConnectionConfig
): Promise<void> {
  return invoke("save_server_config", { config });
}

export async function getServerConfigPath(): Promise<string> {
  return invoke("get_server_config_path");
}

export async function testServerConnection(
  config: ServerConnectionConfig
): Promise<ServerConnectionTestResult> {
  return invoke("test_server_connection", { config });
}

export async function syncServerNow(
  config: ServerConnectionConfig
): Promise<ServerConnectionSyncResult> {
  return invoke("sync_server_now", { config });
}

export async function backupVaultSnapshot(
  config: ServerConnectionConfig,
  vaultRoot: string
): Promise<ServerSnapshotResult> {
  return invoke("backup_vault_snapshot", { config, vaultRoot });
}
