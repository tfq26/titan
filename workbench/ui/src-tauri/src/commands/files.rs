use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::State;

use crate::AppState;

#[derive(Serialize, Deserialize, Clone)]
pub struct DirEntry {
    pub name: String,
    pub is_dir: bool,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ProjectEntry {
    pub id: String,
    pub name: String,
    pub repo_root: String,
    pub vault_root: String,
    pub report_root: String,
    pub status: String,
    pub created: String,
    #[serde(default)]
    pub note: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub standing_instructions: Option<String>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Registry {
    pub projects: Vec<ProjectEntry>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct AddProjectRequest {
    pub project_id: String,
    pub name: String,
    pub repo_root: String,
    pub vault_root: String,
    pub report_root: String,
    pub status: String,
    pub created: String,
    #[serde(default)]
    pub note: Option<String>,
    #[serde(default)]
    pub standing_instructions: Option<String>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ModelEntry {
    pub model_ref: String,
    pub nickname: String,
    pub provider: String,
    pub model_id: String,
    pub env_vars: Vec<String>,
    pub api_key_env: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub base_url_env: Option<String>,
    pub temperature: f64,
    pub max_tokens: u32,
    pub description: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct RoleEntry {
    pub role: String,
    pub model_ref: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct RoutingConfig {
    pub models: Vec<ModelEntry>,
    pub roles: Vec<RoleEntry>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ProjectConfig {
    pub project_id: String,
    pub model_policy: serde_json::Value,
    pub subsystems: Vec<String>,
    pub validation: HashMap<String, String>,
    pub vault: HashMap<String, String>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct QueueState {
    pub open: Vec<TaskSummary>,
    pub claimed: Vec<TaskSummary>,
    pub review_needed: Vec<TaskSummary>,
    pub completed: Vec<TaskSummary>,
    pub blocked: Vec<TaskSummary>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct TaskSummary {
    pub filename: String,
    pub path: String,
    pub status: String,
    pub frontmatter: HashMap<String, serde_json::Value>,
    pub goal: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct TaskDetail {
    pub filename: String,
    pub path: String,
    pub frontmatter: HashMap<String, serde_json::Value>,
    pub content: String,
    pub body: String,
    pub report_content: Option<String>,
    pub review_content: Option<String>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ChatHistorySummary {
    pub project_id: String,
    pub project_name: String,
    pub history_path: String,
    pub archived: bool,
    pub updated_at_ms: u128,
    pub entry_count: usize,
    pub preview: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub current_node: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_decision: Option<String>,
}

fn parse_frontmatter(content: &str) -> (HashMap<String, serde_json::Value>, String) {
    let trimmed = content.trim_start();
    if !trimmed.starts_with("---") {
        return (HashMap::new(), content.to_string());
    }

    let after_first = &trimmed[3..];
    if let Some(end_idx) = after_first.find("\n---") {
        let yaml_str = &after_first[..end_idx];
        let body = &after_first[end_idx + 4..];

        let fm: HashMap<String, serde_json::Value> =
            serde_yaml::from_str(yaml_str).unwrap_or_default();
        (fm, body.trim_start_matches('\n').to_string())
    } else {
        (HashMap::new(), content.to_string())
    }
}

fn extract_goal(body: &str) -> String {
    let mut in_goal = false;
    let mut lines = Vec::new();
    for line in body.lines() {
        if line.starts_with("## Goal") || line.starts_with("# Goal") {
            in_goal = true;
            continue;
        }
        if in_goal {
            if line.starts_with('#') {
                break;
            }
            let trimmed = line.trim();
            if !trimmed.is_empty() {
                lines.push(trimmed.to_string());
            }
            if lines.len() >= 3 {
                break;
            }
        }
    }
    lines.join(" ")
}

fn scan_queue_folder(folder_path: &str, status: &str) -> Vec<TaskSummary> {
    let path = Path::new(folder_path);
    if !path.is_dir() {
        return Vec::new();
    }

    let mut tasks = Vec::new();
    if let Ok(entries) = fs::read_dir(path) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if !name.ends_with(".md") || name == "README.md" {
                continue;
            }
            let full_path = entry.path().to_string_lossy().to_string();
            let content = fs::read_to_string(&full_path).unwrap_or_default();
            let (fm, body) = parse_frontmatter(&content);
            let goal = extract_goal(&body);

            tasks.push(TaskSummary {
                filename: name,
                path: full_path,
                status: status.to_string(),
                frontmatter: fm,
                goal,
            });
        }
    }
    tasks.sort_by(|a, b| b.filename.cmp(&a.filename));
    tasks
}

#[tauri::command]
pub fn read_file(path: String) -> Result<String, String> {
    fs::read_to_string(&path).map_err(|e| format!("Failed to read {}: {}", path, e))
}

#[tauri::command]
pub fn list_dir(path: String) -> Result<Vec<DirEntry>, String> {
    let p = Path::new(&path);
    if !p.is_dir() {
        return Err(format!("{} is not a directory", path));
    }
    let mut entries = Vec::new();
    for entry in fs::read_dir(p).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        entries.push(DirEntry {
            name: entry.file_name().to_string_lossy().to_string(),
            is_dir: entry.file_type().map(|t| t.is_dir()).unwrap_or(false),
        });
    }
    entries.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(entries)
}

#[tauri::command]
pub fn read_registry(state: State<AppState>) -> Result<Registry, String> {
    let path = format!("{}/projects/registry.yaml", state.workbench_root);
    let content = fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read registry: {}", e))?;
    serde_yaml::from_str(&content).map_err(|e| format!("Failed to parse registry: {}", e))
}

#[tauri::command]
pub fn read_project_config(state: State<AppState>, project_id: String) -> Result<ProjectConfig, String> {
    let path = format!("{}/projects/{}/project-config.yaml", state.workbench_root, project_id);
    let content = fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read project config: {}", e))?;
    serde_yaml::from_str(&content).map_err(|e| format!("Failed to parse project config: {}", e))
}

#[tauri::command]
pub fn read_routing(state: State<AppState>) -> Result<RoutingConfig, String> {
    let path = format!("{}/model-routing/routing.yaml", state.workbench_root);
    let content = fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read routing config: {}", e))?;
    let raw: serde_json::Value = serde_yaml::from_str(&content)
        .map_err(|e| format!("Failed to parse routing: {}", e))?;

    let mut models = Vec::new();
    if let Some(model_map) = raw.get("models").and_then(|m| m.as_object()) {
        for (key, val) in model_map {
            models.push(ModelEntry {
                model_ref: key.clone(),
                nickname: val.get("nickname").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                provider: val.get("provider").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                model_id: val.get("model_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                api_key_env: val.get("api_key_env").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                base_url_env: val.get("base_url_env").and_then(|v| v.as_str()).map(String::from),
                temperature: val.get("temperature").and_then(|v| v.as_f64()).unwrap_or(0.0),
                max_tokens: val.get("max_tokens").and_then(|v| v.as_u64()).unwrap_or(4096) as u32,
                description: val.get("description").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                env_vars: {
                    let mut vars = Vec::new();
                    if let Some(v) = val.get("api_key_env").and_then(|v| v.as_str()) {
                        vars.push(v.to_string());
                    }
                    if let Some(v) = val.get("base_url_env").and_then(|v| v.as_str()) {
                        vars.push(v.to_string());
                    }
                    vars
                },
            });
        }
    }

    let mut roles = Vec::new();
    if let Some(role_map) = raw.get("roles").and_then(|r| r.as_object()) {
        for (key, val) in role_map {
            roles.push(RoleEntry {
                role: key.clone(),
                model_ref: val.get("model_ref").and_then(|v| v.as_str()).unwrap_or("").to_string(),
            });
        }
    }

    Ok(RoutingConfig { models, roles })
}

#[tauri::command]
pub fn add_project(
    state: State<AppState>,
    project: AddProjectRequest,
) -> Result<ProjectEntry, String> {
    let registry_path = Path::new(&state.workbench_root).join("projects").join("registry.yaml");
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create registry directory {}: {}", parent.display(), e))?;
    }
    let existing = fs::read_to_string(&registry_path).unwrap_or_else(|_| "projects:\n".to_string());
    let registry: Registry = serde_yaml::from_str(&existing)
        .map_err(|e| format!("Failed to parse registry: {}", e))?;

    let project_id = normalize_project_id(&project.project_id, &project.name, &project.repo_root);
    if project_id.is_empty() {
        return Err("Project ID is required.".to_string());
    }
    if registry.projects.iter().any(|entry| entry.id == project_id) {
        return Err(format!("Project '{}' already exists in the registry.", project_id));
    }

    let repo_root = Path::new(&project.repo_root);
    if !repo_root.exists() {
        return Err(format!("Repo root does not exist: {}", project.repo_root));
    }
    let repo_root = repo_root
        .canonicalize()
        .map_err(|e| format!("Failed to resolve repo root {}: {}", project.repo_root, e))?;

    let vault_root = resolve_project_path(&repo_root, &project.vault_root, "docs/vault");
    let report_root = resolve_project_path(&repo_root, &project.report_root, "docs/reports/subagents");
    let display_name = if project.name.trim().is_empty() {
        repo_root
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or(&project_id)
            .to_string()
    } else {
        project.name.trim().to_string()
    };

    bootstrap_project_dirs(&vault_root, &report_root)?;

    let entry = ProjectEntry {
        id: project_id.clone(),
        name: display_name,
        repo_root: repo_root.to_string_lossy().to_string(),
        vault_root: vault_root.to_string_lossy().to_string(),
        report_root: report_root.to_string_lossy().to_string(),
        status: if project.status.trim().is_empty() {
            "registered".to_string()
        } else {
            project.status.trim().to_string()
        },
        created: project.created.trim().to_string(),
        note: project.note.and_then(|n| empty_to_none(&n)),
        standing_instructions: project
            .standing_instructions
            .and_then(|s| empty_to_none(&s)),
    };

    append_registry_entry(&registry_path, &entry)?;

    let project_dir = Path::new(&state.workbench_root).join("projects").join(&project_id);
    fs::create_dir_all(&project_dir)
        .map_err(|e| format!("Failed to create project config dir {}: {}", project_dir.display(), e))?;
    let project_config_path = project_dir.join("project-config.yaml");
    if !project_config_path.exists() {
        let config = build_project_config_yaml(&entry);
        fs::write(&project_config_path, config)
            .map_err(|e| format!("Failed to write project config {}: {}", project_config_path.display(), e))?;
    }

    Ok(entry)
}

#[tauri::command]
pub fn read_queue(vault_root: String) -> Result<QueueState, String> {
    let base = format!("{}/queue-tasks", vault_root);
    Ok(QueueState {
        open: scan_queue_folder(&format!("{}/open", base), "open"),
        claimed: scan_queue_folder(&format!("{}/claimed", base), "claimed"),
        review_needed: scan_queue_folder(&format!("{}/review-needed", base), "review-needed"),
        completed: scan_queue_folder(&format!("{}/completed", base), "completed"),
        blocked: scan_queue_folder(&format!("{}/blocked", base), "blocked"),
    })
}

#[tauri::command]
pub fn read_task(path: String, vault_root: String) -> Result<TaskDetail, String> {
    let content = fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read task: {}", e))?;
    let (fm, body) = parse_frontmatter(&content);

    let filename = Path::new(&path)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default();

    let task_dir = Path::new(&path).parent().unwrap_or(Path::new(""));

    let report_content = fm.get("report")
        .and_then(|v| v.as_str())
        .and_then(|rel| {
            let resolved = task_dir.join(rel);
            fs::read_to_string(&resolved).ok()
                .or_else(|| {
                    let from_vault = Path::new(&vault_root).join("queue-tasks").join(rel);
                    fs::read_to_string(from_vault).ok()
                })
        });

    let review_content = fm.get("review")
        .and_then(|v| v.as_str())
        .and_then(|rel| {
            let resolved = task_dir.join(rel);
            fs::read_to_string(&resolved).ok()
                .or_else(|| {
                    let from_vault = Path::new(&vault_root).join("queue-tasks").join(rel);
                    fs::read_to_string(from_vault).ok()
                })
        });

    Ok(TaskDetail {
        filename,
        path: path.clone(),
        frontmatter: fm,
        content: content.clone(),
        body,
        report_content,
        review_content,
    })
}

#[tauri::command]
pub fn update_task(
    path: String,
    content: String,
    vault_root: String,
) -> Result<(), String> {
    let path = Path::new(&path);
    ensure_task_path_allowed(path, &vault_root)?;
    fs::write(path, content).map_err(|e| format!("Failed to update task: {}", e))
}

#[tauri::command]
pub fn delete_task(path: String, vault_root: String) -> Result<(), String> {
    let path = Path::new(&path);
    ensure_task_path_allowed(path, &vault_root)?;

    let content = fs::read_to_string(path).unwrap_or_default();
    let (fm, _) = parse_frontmatter(&content);

    let mut targets = vec![path.to_path_buf()];

    let is_review_note = fm
        .get("type")
        .and_then(|v| v.as_str())
        .map(|t| t == "review")
        .unwrap_or(false)
        || path
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.starts_with("review-"))
            .unwrap_or(false);

    if is_review_note {
        if let Some(task_filename) = fm.get("task").and_then(|v| v.as_str()) {
            if let Some(task_path) = find_task_file(&vault_root, task_filename) {
                if !targets.iter().any(|existing| existing == &task_path) {
                    targets.push(task_path);
                }
            }
        }
    }

    for target in targets {
        if target.exists() {
            fs::remove_file(&target)
                .map_err(|e| format!("Failed to delete {}: {}", target.display(), e))?;
        }
    }

    Ok(())
}

fn ensure_task_path_allowed(path: &Path, vault_root: &str) -> Result<(), String> {
    let canonical = path
        .canonicalize()
        .map_err(|e| format!("Failed to resolve task path {}: {}", path.display(), e))?;

    let root = Path::new(vault_root)
        .canonicalize()
        .map_err(|e| format!("Failed to resolve vault root {}: {}", vault_root, e))?;

    if !canonical.starts_with(&root) {
        return Err(format!(
            "Task path {} is outside the vault root {}",
            canonical.display(),
            root.display()
        ));
    }

    if !canonical.to_string_lossy().contains("/queue-tasks/") {
        return Err(format!(
            "Task path {} is not inside a queue-tasks folder",
            canonical.display()
        ));
    }

    Ok(())
}

fn find_task_file(vault_root: &str, filename: &str) -> Option<std::path::PathBuf> {
    let queue_root = Path::new(vault_root).join("queue-tasks");
    for folder in ["open", "claimed", "review-needed", "completed", "blocked"] {
        let candidate = queue_root.join(folder).join(filename);
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
}

fn normalize_project_id(project_id: &str, name: &str, repo_root: &str) -> String {
    let seed = if !project_id.trim().is_empty() {
        project_id.trim().to_string()
    } else if !name.trim().is_empty() {
        name.trim().to_string()
    } else {
        Path::new(repo_root)
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("")
            .to_string()
    };

    seed.to_lowercase()
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect::<String>()
        .split('-')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("-")
}

fn resolve_project_path(repo_root: &Path, provided: &str, fallback_suffix: &str) -> PathBuf {
    if provided.trim().is_empty() {
        repo_root.join(fallback_suffix)
    } else {
        PathBuf::from(provided.trim())
    }
}

fn bootstrap_project_dirs(vault_root: &Path, report_root: &Path) -> Result<(), String> {
    fs::create_dir_all(vault_root)
        .map_err(|e| format!("Failed to create vault root {}: {}", vault_root.display(), e))?;
    fs::create_dir_all(report_root)
        .map_err(|e| format!("Failed to create report root {}: {}", report_root.display(), e))?;

    let queue_root = vault_root.join("queue-tasks");
    for folder in ["open", "claimed", "review-needed", "completed", "blocked"] {
        fs::create_dir_all(queue_root.join(folder))
            .map_err(|e| format!("Failed to create queue folder {}: {}", folder, e))?;
    }

    for folder in ["features", "systems", "memory"] {
        fs::create_dir_all(vault_root.join(folder))
            .map_err(|e| format!("Failed to create vault folder {}: {}", folder, e))?;
    }

    Ok(())
}

fn append_registry_entry(path: &Path, entry: &ProjectEntry) -> Result<(), String> {
    let yaml = serde_yaml::to_string(entry)
        .map_err(|e| format!("Failed to serialize project entry: {}", e))?;
    let mut lines = yaml.trim_end().lines();
    let first = lines
        .next()
        .ok_or_else(|| "Serialized project entry was empty".to_string())?;

    let mut block = String::new();
    block.push_str("  - ");
    block.push_str(first);
    block.push('\n');
    for line in lines {
        block.push_str("    ");
        block.push_str(line);
        block.push('\n');
    }

    let mut existing = if path.exists() {
        fs::read_to_string(path)
            .map_err(|e| format!("Failed to read registry for update: {}", e))?
    } else {
        "projects:\n".to_string()
    };
    if !existing.ends_with('\n') {
        existing.push('\n');
    }
    existing.push_str(&block);
    fs::write(path, existing).map_err(|e| format!("Failed to update registry: {}", e))
}

fn build_project_config_yaml(entry: &ProjectEntry) -> String {
    let mut validation = HashMap::new();
    validation.insert(
        "build".to_string(),
        format!("echo 'Build command not yet configured for {}'", entry.name),
    );
    validation.insert(
        "test".to_string(),
        format!("echo 'Test command not yet configured for {}'", entry.name),
    );

    let mut vault = HashMap::new();
    vault.insert("queue_tasks".to_string(), "queue-tasks".to_string());
    vault.insert("features".to_string(), "features".to_string());
    vault.insert("systems".to_string(), "systems".to_string());
    vault.insert("memory".to_string(), "memory".to_string());
    vault.insert("reports".to_string(), "../reports/subagents".to_string());

    let config = ProjectConfig {
        project_id: entry.id.clone(),
        model_policy: serde_json::json!({
            "allowed_roles": {
                "worker": ["worker_model"],
                "primary_reviewer": ["primary_reviewer_model"],
                "secondary_reviewer": ["secondary_reviewer_model"],
                "classifier": ["classifier_model"],
                "bookkeeping_reviewer": ["bookkeeping_reviewer_model"]
            },
            "denied_model_refs": [],
            "role_requirements": {
                "secondary_reviewer": { "escalation_tier": "high" },
                "bookkeeping_reviewer": { "task_type": ["docs", "bookkeeping"] }
            }
        }),
        subsystems: Vec::new(),
        validation,
        vault,
    };

    serde_yaml::to_string(&config).unwrap_or_default()
}

fn empty_to_none(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

#[tauri::command]
pub fn save_chat_history(
    state: State<AppState>,
    project_id: String,
    history: String,
) -> Result<(), String> {
    let dir = format!("{}/.chat-history", state.workbench_root);
    fs::create_dir_all(&dir).map_err(|e| format!("Failed to create chat dir: {}", e))?;
    let path = format!("{}/{}.json", dir, project_id);
    fs::write(&path, &history).map_err(|e| format!("Failed to save chat: {}", e))
}

#[tauri::command]
pub fn load_chat_history(
    state: State<AppState>,
    project_id: String,
) -> Result<String, String> {
    let path = format!("{}/.chat-history/{}.json", state.workbench_root, project_id);
    fs::read_to_string(&path).or(Ok("[]".to_string()))
}

#[tauri::command]
pub fn start_new_chat(
    state: State<AppState>,
    project_id: String,
    history: String,
) -> Result<(), String> {
    let chat_root = Path::new(&state.workbench_root).join(".chat-history");
    fs::create_dir_all(chat_root.join("archive"))
        .map_err(|e| format!("Failed to create chat archive dir: {}", e))?;

    if history.trim() != "[]" && !history.trim().is_empty() {
        let archive_path = chat_root.join("archive").join(format!(
            "{}__{}.json",
            sanitize_chat_name(&project_id),
            now_ms()
        ));
        fs::write(&archive_path, history)
            .map_err(|e| format!("Failed to archive chat history: {}", e))?;
    }

    let current_path = chat_root.join(format!("{}.json", project_id));
    fs::write(&current_path, "[]")
        .map_err(|e| format!("Failed to clear current chat history: {}", e))
}

#[tauri::command]
pub fn list_chat_histories(state: State<AppState>) -> Result<Vec<ChatHistorySummary>, String> {
    let workbench_root = state.workbench_root.clone();
    let chat_root = Path::new(&workbench_root).join(".chat-history");
    if !chat_root.exists() {
        return Ok(Vec::new());
    }

    let projects = load_project_name_map(&workbench_root);

    let mut summaries = Vec::new();
    collect_chat_history_files(&chat_root, false, &mut summaries, &projects)?;
    collect_chat_history_files(&chat_root.join("archive"), true, &mut summaries, &projects)?;
    summaries.sort_by(|a, b| b.updated_at_ms.cmp(&a.updated_at_ms));
    Ok(summaries)
}

fn collect_chat_history_files(
    dir: &Path,
    archived: bool,
    summaries: &mut Vec<ChatHistorySummary>,
    projects: &HashMap<String, String>,
) -> Result<(), String> {
    if !dir.is_dir() {
        return Ok(());
    }

    for entry in fs::read_dir(dir).map_err(|e| format!("Failed to read {}: {}", dir.display(), e))? {
        let entry = entry.map_err(|e| format!("Failed to read history entry: {}", e))?;
        let path = entry.path();
        if !path.is_file() || path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }

        let content = fs::read_to_string(&path).unwrap_or_else(|_| "[]".to_string());
        let entries: Vec<serde_json::Value> = serde_json::from_str(&content).unwrap_or_default();
        let metadata = entry.metadata().map_err(|e| format!("Failed to read metadata: {}", e))?;
        let updated_at_ms = metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
            .map(|duration| duration.as_millis())
            .unwrap_or(0);

        let (project_id, project_name) = project_from_history_path(&path, archived, projects);
        let (preview, session_id, current_node, final_decision) = summarize_chat_entries(&entries);

        summaries.push(ChatHistorySummary {
            project_id,
            project_name,
            history_path: path.to_string_lossy().to_string(),
            archived,
            updated_at_ms,
            entry_count: entries.len(),
            preview,
            session_id,
            current_node,
            final_decision,
        });
    }

    Ok(())
}

fn load_project_name_map(workbench_root: &str) -> HashMap<String, String> {
    let registry_path = Path::new(workbench_root).join("projects").join("registry.yaml");
    let content = fs::read_to_string(&registry_path).unwrap_or_default();
    let registry: Registry = serde_yaml::from_str(&content).unwrap_or(Registry { projects: vec![] });
    registry
        .projects
        .into_iter()
        .map(|project| (project.id, project.name))
        .collect()
}

fn project_from_history_path(
    path: &Path,
    archived: bool,
    projects: &HashMap<String, String>,
) -> (String, String) {
    let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or_default();
    let project_id = if archived {
        stem.split_once("__").map(|(left, _)| left).unwrap_or(stem)
    } else {
        stem
    }
    .to_string();
    let project_name = projects
        .get(&project_id)
        .cloned()
        .unwrap_or_else(|| project_id.clone());
    (project_id, project_name)
}

fn summarize_chat_entries(
    entries: &[serde_json::Value],
) -> (String, Option<String>, Option<String>, Option<String>) {
    let mut preview = String::new();
    let mut session_id = None;
    let mut current_node = None;
    let mut final_decision = None;

    for entry in entries.iter().rev() {
        if preview.is_empty() {
            if let Some(text) = entry.get("displayText").and_then(|v| v.as_str()).filter(|s| !s.trim().is_empty()) {
                preview = text.trim().to_string();
            } else if let Some(text) = entry.get("content").and_then(|v| v.as_str()).filter(|s| !s.trim().is_empty()) {
                preview = text.trim().to_string();
            }
        }

        if session_id.is_none() || current_node.is_none() || final_decision.is_none() {
            let parsed = entry.get("parsed");
            if session_id.is_none() {
                session_id = parsed
                    .and_then(|p| p.get("session_id"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
            }
            if current_node.is_none() {
                current_node = parsed
                    .and_then(|p| p.get("current_node"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
            }
            if final_decision.is_none() {
                final_decision = parsed
                    .and_then(|p| p.get("final_decision"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
            }
        }

        if !preview.is_empty() && session_id.is_some() && current_node.is_some() && final_decision.is_some() {
            break;
        }
    }

    if preview.is_empty() {
        preview = "Empty chat".to_string();
    } else {
        preview = compact_preview(&preview);
    }

    (preview, session_id, current_node, final_decision)
}

fn compact_preview(text: &str) -> String {
    let mut compact = text.replace('\n', " ").replace('\t', " ");
    compact = compact.split_whitespace().collect::<Vec<_>>().join(" ");
    if compact.chars().count() > 120 {
        compact.chars().take(117).collect::<String>() + "..."
    } else {
        compact
    }
}

fn sanitize_chat_name(name: &str) -> String {
    name.chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '-' })
        .collect()
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}
