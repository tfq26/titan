use serde::Serialize;
use std::collections::HashSet;
use std::path::Path;
use std::fs;
use tauri::State;
use rfd::FileDialog;

use crate::AppState;

#[derive(Serialize)]
pub struct EnvVarStatus {
    pub name: String,
    pub present: bool,
    pub in_file: bool,
}

#[derive(Serialize)]
pub struct TraceConfig {
    pub tracing_enabled: bool,
    pub project_name: Option<String>,
    pub endpoint: Option<String>,
}

fn parse_secrets_file_vars(path: &Path) -> HashSet<String> {
    let mut vars = HashSet::new();
    if let Ok(content) = fs::read_to_string(path) {
        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with('#') || trimmed.is_empty() {
                continue;
            }
            let stripped = trimmed.strip_prefix("export ").unwrap_or(trimmed);
            if let Some(eq_pos) = stripped.find('=') {
                let var_name = stripped[..eq_pos].trim();
                if !var_name.is_empty() {
                    vars.insert(var_name.to_string());
                }
            }
        }
    }
    vars
}

#[tauri::command]
pub fn check_env_vars(state: State<AppState>, names: Vec<String>) -> Vec<EnvVarStatus> {
    let secrets_path = Path::new(&state.workbench_root)
        .join(".workbench-secrets.env");
    let file_vars = parse_secrets_file_vars(&secrets_path);

    names
        .into_iter()
        .map(|name| {
            let present = std::env::var(&name).is_ok();
            let in_file = file_vars.contains(&name);
            EnvVarStatus { name, present, in_file }
        })
        .collect()
}

#[tauri::command]
pub fn open_path(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open: {}", e))?;
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open: {}", e))?;
    }
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("explorer")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open: {}", e))?;
    }
    Ok(())
}

#[tauri::command]
pub fn pick_folder() -> Result<Option<String>, String> {
    let folder = FileDialog::new()
        .set_title("Choose a project folder")
        .pick_folder();

    Ok(folder.map(|path| path.to_string_lossy().to_string()))
}

#[tauri::command]
pub fn get_workbench_root(state: State<AppState>) -> String {
    state.workbench_root.clone()
}

#[derive(Serialize)]
pub struct SecretsFileStatus {
    pub path: String,
    pub exists: bool,
}

#[tauri::command]
pub fn check_secrets_file(state: State<AppState>) -> SecretsFileStatus {
    let secrets_path = Path::new(&state.workbench_root).join(".workbench-secrets.env");
    SecretsFileStatus {
        path: secrets_path.to_string_lossy().to_string(),
        exists: secrets_path.exists(),
    }
}

pub fn load_env_from_secrets(workbench_root: &str) -> u32 {
    let secrets_path = Path::new(workbench_root)
        .join(".workbench-secrets.env");

    let content = match fs::read_to_string(&secrets_path) {
        Ok(c) => c,
        Err(_) => return 0,
    };

    let mut count = 0u32;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('#') || trimmed.is_empty() {
            continue;
        }
        let stripped = trimmed.strip_prefix("export ").unwrap_or(trimmed);
        if let Some(eq_pos) = stripped.find('=') {
            let var_name = stripped[..eq_pos].trim();
            let var_value = stripped[eq_pos + 1..].trim();
            let var_value = var_value.trim_matches('"').trim_matches('\'');
            if !var_name.is_empty() {
                std::env::set_var(var_name, var_value);
                count += 1;
            }
        }
    }
    count
}

#[tauri::command]
pub fn load_secrets_file(state: State<AppState>) -> Result<u32, String> {
    Ok(load_env_from_secrets(&state.workbench_root))
}

#[tauri::command]
pub fn get_trace_config() -> TraceConfig {
    let tracing_v2 = std::env::var("LANGCHAIN_TRACING_V2")
        .map(|v| v == "true")
        .unwrap_or(false);

    let project_name = std::env::var("LANGCHAIN_PROJECT").ok();
    let endpoint = std::env::var("LANGCHAIN_ENDPOINT").ok();

    TraceConfig {
        tracing_enabled: tracing_v2,
        project_name,
        endpoint,
    }
}
