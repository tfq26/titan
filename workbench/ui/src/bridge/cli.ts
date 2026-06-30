import { invoke } from "@tauri-apps/api/core";
import type { CommandResult } from "../types";

export async function runRequest(
  projectId: string,
  request: string
): Promise<CommandResult> {
  return invoke("run_request", { projectId, request });
}

export async function runChat(
  projectId: string,
  message: string,
  role?: string,
  responseMode?: "brief" | "explain",
  chatContext?: string
): Promise<CommandResult> {
  return invoke("run_chat", { projectId, message, role, responseMode, chatContext });
}

export async function resumeSession(
  projectId: string,
  sessionId: string
): Promise<CommandResult> {
  return invoke("resume_session", { projectId, sessionId });
}

export async function runDriftScan(
  projectId: string
): Promise<CommandResult> {
  return invoke("run_drift_scan", { projectId });
}

export async function startWatcher(
  projectId: string,
  interval?: number
): Promise<string> {
  return invoke("start_watcher", { projectId, interval });
}

export async function stopWatcher(): Promise<string> {
  return invoke("stop_watcher");
}

export async function resumeWithResponse(
  projectId: string,
  sessionId: string,
  response: string
): Promise<CommandResult> {
  return invoke("resume_with_response", { projectId, sessionId, response });
}

export async function runDiscourse(
  projectId: string,
  request: string,
  roles?: string
): Promise<void> {
  return invoke("run_discourse", { projectId, request, roles: roles ?? null });
}
