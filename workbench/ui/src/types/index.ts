export interface ProjectEntry {
  id: string;
  name: string;
  repo_root: string;
  vault_root: string;
  report_root: string;
  status: string;
  created: string;
  note?: string;
  standing_instructions?: string;
}

export interface ProjectAddInput {
  project_id: string;
  name: string;
  repo_root: string;
  vault_root: string;
  report_root: string;
  status: string;
  created: string;
  note?: string;
  standing_instructions?: string;
}

export interface Registry {
  projects: ProjectEntry[];
}

export interface ModelEntry {
  model_ref: string;
  nickname: string;
  provider: string;
  model_id: string;
  env_vars: string[];
  api_key_env: string;
  base_url_env?: string;
  temperature: number;
  max_tokens: number;
  description: string;
}

export interface RoleEntry {
  role: string;
  model_ref: string;
}

export interface RoutingConfig {
  models: ModelEntry[];
  roles: RoleEntry[];
}

export interface ModelConfig {
  provider: string;
  api_key_env: string;
  base_url_env?: string;
  model_id: string;
  nickname: string;
  temperature: number;
  max_tokens: number;
  description: string;
}

export interface ProjectModelPolicy {
  allowed_roles: Record<string, string[]>;
  denied_model_refs: string[];
  role_requirements?: Record<string, Record<string, unknown>>;
}

export interface ProjectConfig {
  project_id: string;
  model_policy: Record<string, unknown>;
  subsystems: string[];
  validation: Record<string, string>;
  vault: Record<string, string>;
}

export interface TaskSummary {
  filename: string;
  path: string;
  status: string;
  frontmatter: Record<string, unknown>;
  goal: string;
}

export interface QueueState {
  open: TaskSummary[];
  claimed: TaskSummary[];
  review_needed: TaskSummary[];
  completed: TaskSummary[];
  blocked: TaskSummary[];
}

export interface TaskDetail {
  filename: string;
  path: string;
  frontmatter: Record<string, unknown>;
  content: string;
  body: string;
  report_content: string | null;
  review_content: string | null;
}

export interface ChatHistorySummary {
  project_id: string;
  project_name: string;
  history_path: string;
  archived: boolean;
  updated_at_ms: number;
  entry_count: number;
  preview: string;
  session_id: string | null;
  current_node: string | null;
  final_decision: string | null;
}

export interface ChatSessionSummary {
  project_id: string;
  current_speaker: string;
  current_role: string;
  response_mode: ResponseMode;
  relay_enabled: boolean;
  turn_count: number;
  preview: string;
  state: "idle" | "waiting" | "responding" | "active";
}

export interface CommandResult {
  stdout: string;
  stderr: string;
  exit_code: number | null;
}

export interface EnvVarStatus {
  name: string;
  present: boolean;
  in_file: boolean;
}

export interface TraceConfig {
  tracing_enabled: boolean;
  project_name: string | null;
  endpoint: string | null;
}

export interface ServerConnectionConfig {
  enabled: boolean;
  profile_name: string;
  base_url: string;
  project_key: string;
  auth_header: string;
  auth_token: string;
  health_path: string;
  events_path: string;
  snapshots_path: string;
  sync_interval_seconds: number;
}

export interface ServerConnectionTestResult {
  ok: boolean;
  status_code: number | null;
  message: string;
  tested_url: string;
}

export interface ServerConnectionSyncResult {
  ok: boolean;
  health_status_code: number | null;
  events_status_code: number | null;
  health_url: string;
  events_url: string;
  message: string;
  event_id: string;
  response_excerpt: string | null;
}

export interface ServerSnapshotResult {
  ok: boolean;
  status_code: number | null;
  snapshot_url: string;
  snapshot_id: string;
  file_count: number;
  message: string;
  response_excerpt: string | null;
}

export type QueueColumn = "open" | "claimed" | "review_needed" | "completed" | "blocked";

export interface DiscourseLinePayload {
  text: string;
  stream: "stdout" | "stderr";
}

export interface DiscourseCompletePayload {
  exit_code: number | null;
}

export interface DiscourseStartPayload {
  participants: string;
  nicknames: string;
  request: string;
  project: string;
}

export interface DiscourseTurnStartPayload {
  role: string;
  nickname: string;
  turn: number;
}

export interface DiscourseTokenPayload {
  role: string;
  text: string;
}

export interface DiscourseTurnEndPayload {
  role: string;
  text: string;
  input_tokens?: number;
  output_tokens?: number;
}

export interface DiscourseDonePayload {
  consensus: boolean;
  ready_to_queue: boolean;
}

export type PanelTab =
  | "chat"
  | "queue"
  | "task"
  | "configure";

export type SessionMode =
  | "general"
  | "plan"
  | "queue"
  | "review"
  | "ask";

export type ResponseMode = "brief" | "explain";

export const SESSION_MODE_LABELS: Record<SessionMode, string> = {
  general: "General Request",
  plan: "Plan Kickoff",
  queue: "Queue Task",
  review: "Review Work",
  ask: "Ask Team",
};

export const PROVIDERS = ["google", "openai", "openai_compatible", "anthropic"] as const;

export const ROLES = [
  "worker",
  "primary_reviewer",
  "secondary_reviewer",
  "classifier",
  "bookkeeping_reviewer",
] as const;

export function emptyModelConfig(): ModelConfig {
  return {
    provider: "google",
    api_key_env: "",
    model_id: "",
    nickname: "",
    temperature: 0.2,
    max_tokens: 8192,
    description: "",
  };
}

export function modelEntryToConfig(entry: ModelEntry): ModelConfig {
  return {
    provider: entry.provider,
    api_key_env: entry.api_key_env,
    base_url_env: entry.base_url_env,
    model_id: entry.model_id,
    nickname: entry.nickname,
    temperature: entry.temperature,
    max_tokens: entry.max_tokens,
    description: entry.description,
  };
}

export function defaultServerConnectionConfig(): ServerConnectionConfig {
  return {
    enabled: false,
    profile_name: "local-server",
    base_url: "http://127.0.0.1:8787",
    project_key: "",
    auth_header: "Authorization",
    auth_token: "",
    health_path: "/health",
    events_path: "/events",
    snapshots_path: "/snapshots",
    sync_interval_seconds: 15,
  };
}
