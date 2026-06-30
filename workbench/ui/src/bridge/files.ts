import { invoke } from "@tauri-apps/api/core";
import type {
  Registry,
  ProjectConfig,
  RoutingConfig,
  QueueState,
  TaskDetail,
  ProjectAddInput,
  ProjectEntry,
  ChatHistorySummary,
} from "../types";

export async function readRegistry(): Promise<Registry> {
  return invoke("read_registry");
}

export async function readProjectConfig(
  projectId: string
): Promise<ProjectConfig> {
  return invoke("read_project_config", { projectId });
}

export async function readRouting(): Promise<RoutingConfig> {
  return invoke("read_routing");
}

export async function readQueue(vaultRoot: string): Promise<QueueState> {
  return invoke("read_queue", { vaultRoot });
}

export async function readTask(
  path: string,
  vaultRoot: string
): Promise<TaskDetail> {
  return invoke("read_task", { path, vaultRoot });
}

export async function readFile(path: string): Promise<string> {
  return invoke("read_file", { path });
}

export async function saveChatHistory(
  projectId: string,
  history: string
): Promise<void> {
  return invoke("save_chat_history", { projectId, history });
}

export async function loadChatHistory(
  projectId: string
): Promise<string> {
  return invoke("load_chat_history", { projectId });
}

export async function startNewChat(
  projectId: string,
  history: string
): Promise<void> {
  return invoke("start_new_chat", { projectId, history });
}

export async function listChatHistories(): Promise<ChatHistorySummary[]> {
  return invoke("list_chat_histories");
}

export async function addProject(
  project: ProjectAddInput
): Promise<ProjectEntry> {
  return invoke("add_project", { project });
}

export async function updateTask(
  path: string,
  content: string,
  vaultRoot: string
): Promise<void> {
  return invoke("update_task", { path, content, vaultRoot });
}

export async function deleteTask(
  path: string,
  vaultRoot: string
): Promise<void> {
  return invoke("delete_task", { path, vaultRoot });
}
