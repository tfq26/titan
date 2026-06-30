use keyring::Keyring;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

const KEYRING_SERVICE: &str = "workbench-console.server-config";
const CURL_MARKER: &str = "__WORKBENCH_HTTP_STATUS__:";

#[derive(Serialize, Deserialize, Clone)]
pub struct ServerConnectionConfig {
    pub enabled: bool,
    pub profile_name: String,
    pub base_url: String,
    pub project_key: String,
    pub auth_header: String,
    pub auth_token: String,
    pub health_path: String,
    pub events_path: String,
    pub snapshots_path: String,
    pub sync_interval_seconds: u32,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ServerConnectionTestResult {
    pub ok: bool,
    pub status_code: Option<u16>,
    pub message: String,
    pub tested_url: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ServerConnectionSyncResult {
    pub ok: bool,
    pub health_status_code: Option<u16>,
    pub events_status_code: Option<u16>,
    pub health_url: String,
    pub events_url: String,
    pub message: String,
    pub event_id: String,
    pub response_excerpt: Option<String>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ServerSnapshotResult {
    pub ok: bool,
    pub status_code: Option<u16>,
    pub snapshot_url: String,
    pub snapshot_id: String,
    pub file_count: usize,
    pub message: String,
    pub response_excerpt: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Default)]
struct PersistedServerConnectionConfig {
    pub enabled: bool,
    pub profile_name: String,
    pub base_url: String,
    pub project_key: String,
    pub auth_header: String,
    pub health_path: String,
    pub events_path: String,
    pub snapshots_path: String,
    pub sync_interval_seconds: u32,
}

#[derive(Serialize)]
struct ServerEventEnvelope {
    event_id: String,
    event_type: String,
    profile_name: String,
    project_key: String,
    source: String,
    created_at_ms: u128,
    payload: Value,
}

#[derive(Serialize)]
struct VaultSnapshotEnvelope {
    snapshot_id: String,
    snapshot_type: String,
    profile_name: String,
    project_key: String,
    source: String,
    created_at_ms: u128,
    vault_root: String,
    summary: VaultSnapshotSummary,
    files: Vec<VaultFileEntry>,
}

#[derive(Serialize)]
struct VaultSnapshotSummary {
    file_count: usize,
    queue_counts: std::collections::BTreeMap<String, usize>,
}

#[derive(Serialize)]
struct VaultFileEntry {
    path: String,
    size_bytes: u64,
    modified_at_ms: Option<u128>,
    content: String,
}

#[derive(Debug)]
struct CurlResponse {
    status_code: Option<u16>,
    body: String,
}

fn server_config_path() -> Result<PathBuf, String> {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map_err(|_| "Could not determine home directory".to_string())?;
    Ok(PathBuf::from(home)
        .join(".workbench-console")
        .join("server-config.json"))
}

fn token_entry(path: &Path) -> Keyring<'static> {
    let username = path.to_string_lossy().to_string();
    let username = Box::leak(username.into_boxed_str());
    Keyring::new(KEYRING_SERVICE, username)
}

#[tauri::command]
pub fn get_server_config_path() -> Result<String, String> {
    Ok(server_config_path()?.to_string_lossy().to_string())
}

#[tauri::command]
pub fn load_server_config() -> Result<Option<ServerConnectionConfig>, String> {
    let path = server_config_path()?;
    if !path.exists() {
        return Ok(None);
    }

    let content = fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read server config {}: {}", path.display(), e))?;
    let persisted: PersistedServerConnectionConfig = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse server config {}: {}", path.display(), e))?;
    let auth_token = token_entry(&path).get_password().unwrap_or_default();

    Ok(Some(ServerConnectionConfig {
        enabled: persisted.enabled,
        profile_name: persisted.profile_name,
        base_url: persisted.base_url,
        project_key: persisted.project_key,
        auth_header: persisted.auth_header,
        auth_token,
        health_path: persisted.health_path,
        events_path: persisted.events_path,
        snapshots_path: persisted.snapshots_path,
        sync_interval_seconds: persisted.sync_interval_seconds,
    }))
}

#[tauri::command]
pub fn save_server_config(config: ServerConnectionConfig) -> Result<(), String> {
    let path = server_config_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create server config dir {}: {}", parent.display(), e))?;
    }

    let persisted = PersistedServerConnectionConfig {
        enabled: config.enabled,
        profile_name: config.profile_name.trim().to_string(),
        base_url: config.base_url.trim().trim_end_matches('/').to_string(),
        project_key: config.project_key.trim().to_string(),
        auth_header: if config.auth_header.trim().is_empty() {
            "Authorization".to_string()
        } else {
            config.auth_header.trim().to_string()
        },
        health_path: normalize_path(&config.health_path),
        events_path: normalize_path(&config.events_path),
        snapshots_path: normalize_path(&config.snapshots_path),
        sync_interval_seconds: config.sync_interval_seconds.max(5),
    };

    let content = serde_json::to_string_pretty(&persisted)
        .map_err(|e| format!("Failed to serialize server config: {}", e))?;
    fs::write(&path, content)
        .map_err(|e| format!("Failed to write server config {}: {}", path.display(), e))?;

    let entry = token_entry(&path);
    if config.auth_token.trim().is_empty() {
        let _ = entry.delete_password();
    } else {
        entry
            .set_password(config.auth_token.trim())
            .map_err(|e| format!("Failed to store server token in keyring: {}", e))?;
    }

    Ok(())
}

#[tauri::command]
pub fn test_server_connection(
    config: ServerConnectionConfig,
) -> Result<ServerConnectionTestResult, String> {
    let normalized = normalize_config(config);
    let health_url = join_url(&normalized.base_url, &normalized.health_path);
    let response = curl_request("GET", &health_url, &request_headers(&normalized), None)?;
    let ok = is_success_status(response.status_code);
    let message = if ok {
        "Server responded successfully.".to_string()
    } else {
        format!(
            "Server health check returned {}.",
            response
                .status_code
                .map(|code| code.to_string())
                .unwrap_or_else(|| "no HTTP status".to_string())
        )
    };

    Ok(ServerConnectionTestResult {
        ok,
        status_code: response.status_code,
        message,
        tested_url: health_url,
    })
}

#[tauri::command]
pub fn sync_server_now(config: ServerConnectionConfig) -> Result<ServerConnectionSyncResult, String> {
    let normalized = normalize_config(config);
    if !normalized.enabled {
        return Ok(ServerConnectionSyncResult {
            ok: false,
            health_status_code: None,
            events_status_code: None,
            health_url: join_url(&normalized.base_url, &normalized.health_path),
            events_url: join_url(&normalized.base_url, &normalized.events_path),
            message: "Server sync is disabled in the profile.".to_string(),
            event_id: generate_event_id(),
            response_excerpt: None,
        });
    }

    let health_url = join_url(&normalized.base_url, &normalized.health_path);
    let health = curl_request("GET", &health_url, &request_headers(&normalized), None)?;
    if !is_success_status(health.status_code) {
        return Ok(ServerConnectionSyncResult {
            ok: false,
            health_status_code: health.status_code,
            events_status_code: None,
            health_url,
            events_url: join_url(&normalized.base_url, &normalized.events_path),
            message: format!(
                "Health check failed before sync could start (status {}).",
                health
                    .status_code
                    .map(|code| code.to_string())
                    .unwrap_or_else(|| "unknown".to_string())
            ),
            event_id: generate_event_id(),
            response_excerpt: Some(excerpt(&health.body)),
        });
    }

    let profile_name = normalized.profile_name.clone();
    let project_key = normalized.project_key.clone();
    let base_url = normalized.base_url.clone();
    let health_path = normalized.health_path.clone();
    let events_path = normalized.events_path.clone();
    let snapshots_path = normalized.snapshots_path.clone();
    let event_id = generate_event_id();
    let events_url = join_url(&normalized.base_url, &normalized.events_path);
    let envelope = ServerEventEnvelope {
        event_id: event_id.clone(),
        event_type: "connection_probe".to_string(),
        profile_name: profile_name.clone(),
        project_key: project_key.clone(),
        source: "workbench-console".to_string(),
        created_at_ms: now_ms(),
        payload: json!({
            "kind": "server_sync_probe",
            "project_key": project_key,
            "profile_name": profile_name,
            "base_url": base_url,
            "health_path": health_path,
            "events_path": events_path,
            "snapshots_path": snapshots_path,
        }),
    };
    let body = serde_json::to_string(&envelope)
        .map_err(|e| format!("Failed to serialize sync envelope: {}", e))?;
    let response = curl_request(
        "POST",
        &events_url,
        &request_headers(&normalized),
        Some((&body, "application/json")),
    )?;
    let ok = is_success_status(response.status_code);
    let message = if ok {
        "Connection probe synced to the server.".to_string()
    } else {
        format!(
            "Server sync returned {}.",
            response
                .status_code
                .map(|code| code.to_string())
                .unwrap_or_else(|| "no HTTP status".to_string())
        )
    };

    Ok(ServerConnectionSyncResult {
        ok,
        health_status_code: health.status_code,
        events_status_code: response.status_code,
        health_url,
        events_url,
        message,
        event_id,
        response_excerpt: Some(excerpt(&response.body)),
    })
}

#[tauri::command]
pub fn backup_vault_snapshot(
    config: ServerConnectionConfig,
    vault_root: String,
) -> Result<ServerSnapshotResult, String> {
    let normalized = normalize_config(config);
    if !normalized.enabled {
        return Ok(ServerSnapshotResult {
            ok: false,
            status_code: None,
            snapshot_url: join_url(&normalized.base_url, &normalized.snapshots_path),
            snapshot_id: generate_snapshot_id(),
            file_count: 0,
            message: "Server sync is disabled in the profile.".to_string(),
            response_excerpt: None,
        });
    }

    let vault_root = PathBuf::from(vault_root);
    if !vault_root.exists() {
        return Err(format!("Vault root does not exist: {}", vault_root.display()));
    }

    let snapshot = collect_vault_snapshot(&vault_root)?;
    let snapshot_url = join_url(&normalized.base_url, &normalized.snapshots_path);
    let payload = VaultSnapshotEnvelope {
        snapshot_id: generate_snapshot_id(),
        snapshot_type: "vault_backup".to_string(),
        profile_name: normalized.profile_name.clone(),
        project_key: normalized.project_key.clone(),
        source: "workbench-console".to_string(),
        created_at_ms: now_ms(),
        vault_root: vault_root.to_string_lossy().to_string(),
        summary: VaultSnapshotSummary {
            file_count: snapshot.files.len(),
            queue_counts: snapshot.queue_counts,
        },
        files: snapshot.files,
    };
    let body = serde_json::to_string(&payload)
        .map_err(|e| format!("Failed to serialize vault snapshot: {}", e))?;
    let response = curl_request(
        "POST",
        &snapshot_url,
        &request_headers(&normalized),
        Some((&body, "application/json")),
    )?;
    let ok = is_success_status(response.status_code);
    let message = if ok {
        format!("Uploaded {} vault file(s) as a server backup.", payload.summary.file_count)
    } else {
        format!(
            "Server snapshot upload returned {}.",
            response
                .status_code
                .map(|code| code.to_string())
                .unwrap_or_else(|| "no HTTP status".to_string())
        )
    };

    Ok(ServerSnapshotResult {
        ok,
        status_code: response.status_code,
        snapshot_url,
        snapshot_id: payload.snapshot_id,
        file_count: payload.summary.file_count,
        message,
        response_excerpt: Some(excerpt(&response.body)),
    })
}

fn normalize_config(mut config: ServerConnectionConfig) -> ServerConnectionConfig {
    config.profile_name = config.profile_name.trim().to_string();
    config.base_url = config.base_url.trim().trim_end_matches('/').to_string();
    config.project_key = config.project_key.trim().to_string();
    config.auth_header = config.auth_header.trim().to_string();
    config.auth_token = config.auth_token.trim().to_string();
    config.health_path = normalize_path(&config.health_path);
    config.events_path = normalize_path(&config.events_path);
    config.snapshots_path = normalize_path(&config.snapshots_path);
    config.sync_interval_seconds = config.sync_interval_seconds.max(5);
    if config.auth_header.is_empty() {
        config.auth_header = "Authorization".to_string();
    }
    config
}

fn request_headers(config: &ServerConnectionConfig) -> Vec<String> {
    let mut headers = vec![];
    if !config.auth_token.trim().is_empty() {
        let header_value = if config.auth_header.eq_ignore_ascii_case("authorization")
            && !config.auth_token.trim().starts_with("Bearer ")
        {
            format!("Authorization: Bearer {}", config.auth_token.trim())
        } else {
            format!("{}: {}", config.auth_header, config.auth_token.trim())
        };
        headers.push(header_value);
    }
    headers
}

fn join_url(base_url: &str, path: &str) -> String {
    format!(
        "{}/{}",
        base_url.trim_end_matches('/'),
        path.trim_start_matches('/')
    )
}

fn curl_request(
    method: &str,
    url: &str,
    headers: &[String],
    body: Option<(&str, &str)>,
) -> Result<CurlResponse, String> {
    let mut command = Command::new("curl");
    command
        .arg("--silent")
        .arg("--show-error")
        .arg("--location")
        .arg("--request")
        .arg(method)
        .arg("--write-out")
        .arg(format!("\n{}%{{http_code}}", CURL_MARKER));

    for header in headers {
        command.arg("--header").arg(header);
    }

    let child = if let Some((body, content_type)) = body {
        command
            .arg("--header")
            .arg(format!("Content-Type: {}", content_type))
            .arg("--data-binary")
            .arg("@-")
            .stdin(Stdio::piped());
        let mut child = command
            .arg(url)
            .spawn()
            .map_err(|e| format!("Failed to start curl: {}", e))?;
        if let Some(mut stdin) = child.stdin.take() {
            stdin
                .write_all(body.as_bytes())
                .map_err(|e| format!("Failed to write request body: {}", e))?;
        }
        child
    } else {
        command
            .arg(url)
            .spawn()
            .map_err(|e| format!("Failed to start curl: {}", e))?
    };

    let output = child
        .wait_with_output()
        .map_err(|e| format!("Failed to wait for curl: {}", e))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if stderr.is_empty() {
            format!(
                "curl exited with status {}",
                output.status.code().map(|code| code.to_string()).unwrap_or_else(|| "unknown".to_string())
            )
        } else {
            format!(
                "curl exited with status {}: {}",
                output.status.code().map(|code| code.to_string()).unwrap_or_else(|| "unknown".to_string()),
                stderr
            )
        });
    }

    let combined = String::from_utf8_lossy(&output.stdout).to_string();
    let (body, status_code) = parse_curl_output(&combined);
    Ok(CurlResponse { status_code, body })
}

fn parse_curl_output(output: &str) -> (String, Option<u16>) {
    if let Some(index) = output.rfind(CURL_MARKER) {
        let body = output[..index].trim_end_matches('\n').to_string();
        let status_text = output[index + CURL_MARKER.len()..].trim();
        let status_code = status_text.parse::<u16>().ok();
        (body, status_code)
    } else {
        (output.to_string(), None)
    }
}

fn excerpt(body: &str) -> String {
    let trimmed = body.trim();
    if trimmed.chars().count() <= 240 {
        trimmed.to_string()
    } else {
        trimmed.chars().take(240).collect::<String>() + "..."
    }
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

fn generate_event_id() -> String {
    format!("wb-{}", now_ms())
}

fn generate_snapshot_id() -> String {
    format!("snapshot-{}", now_ms())
}

fn normalize_path(path: &str) -> String {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        "/".to_string()
    } else if trimmed.starts_with('/') {
        trimmed.to_string()
    } else {
        format!("/{}", trimmed)
    }
}

struct VaultSnapshot {
    files: Vec<VaultFileEntry>,
    queue_counts: std::collections::BTreeMap<String, usize>,
}

fn collect_vault_snapshot(vault_root: &Path) -> Result<VaultSnapshot, String> {
    let mut snapshot = VaultSnapshot {
        files: Vec::new(),
        queue_counts: std::collections::BTreeMap::new(),
    };
    walk_vault(vault_root, vault_root, &mut snapshot)?;
    snapshot.files.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(snapshot)
}

fn walk_vault(root: &Path, dir: &Path, snapshot: &mut VaultSnapshot) -> Result<(), String> {
    for entry in fs::read_dir(dir)
        .map_err(|e| format!("Failed to read vault directory {}: {}", dir.display(), e))?
    {
        let entry = entry.map_err(|e| format!("Failed to read vault entry: {}", e))?;
        let path = entry.path();
        let file_name = entry.file_name();
        let file_name = file_name.to_string_lossy();

        if path.is_dir() {
            if should_skip_dir(&file_name) {
                continue;
            }
            walk_vault(root, &path, snapshot)?;
            continue;
        }

        if !path.is_file() || !is_text_snapshot_file(&path) {
            continue;
        }

        let relative = path
            .strip_prefix(root)
            .map_err(|e| format!("Failed to compute relative path for {}: {}", path.display(), e))?;
        let content = match fs::read_to_string(&path) {
            Ok(content) => content,
            Err(_) => continue,
        };
        let metadata = fs::metadata(&path)
            .map_err(|e| format!("Failed to stat {}: {}", path.display(), e))?;
        let modified_at_ms = metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
            .map(|duration| duration.as_millis());

        increment_queue_count(relative, snapshot);
        snapshot.files.push(VaultFileEntry {
            path: relative.to_string_lossy().replace('\\', "/"),
            size_bytes: metadata.len(),
            modified_at_ms,
            content,
        });
    }
    Ok(())
}

fn should_skip_dir(name: &str) -> bool {
    matches!(
        name,
        ".git" | ".obsidian" | ".venv" | "node_modules" | "target" | "dist" | "build"
    ) || name.starts_with('.')
}

fn is_text_snapshot_file(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|ext| ext.to_str()).unwrap_or("").to_ascii_lowercase().as_str(),
        "md" | "markdown" | "yaml" | "yml" | "json" | "txt" | "toml" | "csv" | "ts" | "tsx" | "js" | "jsx" | "rs" | "py"
    )
}

fn increment_queue_count(relative: &Path, snapshot: &mut VaultSnapshot) {
    let rel = relative.to_string_lossy().replace('\\', "/");
    if rel.starts_with("queue-tasks/open/") {
        *snapshot.queue_counts.entry("open".to_string()).or_insert(0) += 1;
    } else if rel.starts_with("queue-tasks/claimed/") {
        *snapshot.queue_counts.entry("claimed".to_string()).or_insert(0) += 1;
    } else if rel.starts_with("queue-tasks/review-needed/") {
        *snapshot.queue_counts.entry("review-needed".to_string()).or_insert(0) += 1;
    } else if rel.starts_with("queue-tasks/completed/") {
        *snapshot.queue_counts.entry("completed".to_string()).or_insert(0) += 1;
    } else if rel.starts_with("queue-tasks/blocked/") {
        *snapshot.queue_counts.entry("blocked".to_string()).or_insert(0) += 1;
    }
}

fn is_success_status(status_code: Option<u16>) -> bool {
    matches!(status_code, Some(code) if (200..300).contains(&code))
}
