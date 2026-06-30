import { invoke } from "@tauri-apps/api/core";
import type { ModelConfig, ProjectModelPolicy } from "../types";

export async function addModel(
  modelRef: string,
  config: ModelConfig
): Promise<void> {
  return invoke("add_model", { modelRef, config });
}

export async function updateModel(
  modelRef: string,
  config: ModelConfig
): Promise<void> {
  return invoke("update_model", { modelRef, config });
}

export async function removeModel(modelRef: string): Promise<void> {
  return invoke("remove_model", { modelRef });
}

export async function updateRoleAssignment(
  role: string,
  modelRef: string
): Promise<void> {
  return invoke("update_role_assignment", { role, modelRef });
}

export async function updateProjectModelPolicy(
  projectId: string,
  policy: ProjectModelPolicy
): Promise<void> {
  return invoke("update_project_model_policy", { projectId, policy });
}
