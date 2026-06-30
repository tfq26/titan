import { invoke } from "@tauri-apps/api/core";
import type { EnvVarStatus, TraceConfig } from "../types";

export async function checkEnvVars(
  names: string[]
): Promise<EnvVarStatus[]> {
  return invoke("check_env_vars", { names });
}

export async function openPath(path: string): Promise<void> {
  return invoke("open_path", { path });
}

export async function pickFolder(): Promise<string | null> {
  return invoke("pick_folder");
}

export async function getWorkbenchRoot(): Promise<string> {
  return invoke("get_workbench_root");
}

export async function getTraceConfig(): Promise<TraceConfig> {
  return invoke("get_trace_config");
}

export async function checkSecretsFile(): Promise<{
  path: string;
  exists: boolean;
}> {
  return invoke("check_secrets_file");
}

export async function loadSecretsFile(): Promise<number> {
  return invoke("load_secrets_file");
}
