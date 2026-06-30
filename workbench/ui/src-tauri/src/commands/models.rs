use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use tauri::State;

use crate::AppState;

#[derive(Serialize, Deserialize, Clone)]
pub struct ModelConfig {
    pub provider: String,
    pub api_key_env: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub base_url_env: Option<String>,
    pub model_id: String,
    pub nickname: String,
    pub temperature: f64,
    pub max_tokens: u32,
    pub description: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ProjectModelPolicy {
    pub allowed_roles: HashMap<String, Vec<String>>,
    pub denied_model_refs: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role_requirements: Option<serde_json::Value>,
}

const VALID_PROVIDERS: &[&str] = &["google", "openai", "openai_compatible", "anthropic"];
const VALID_ROLES: &[&str] = &[
    "worker",
    "primary_reviewer",
    "secondary_reviewer",
    "classifier",
    "bookkeeping_reviewer",
];

fn routing_path(root: &str) -> String {
    format!("{}/model-routing/routing.yaml", root)
}

fn project_config_path(root: &str, project_id: &str) -> String {
    format!("{}/projects/{}/project-config.yaml", root, project_id)
}

fn read_yaml(path: &str) -> Result<serde_yaml::Value, String> {
    let content =
        fs::read_to_string(path).map_err(|e| format!("Failed to read {}: {}", path, e))?;
    serde_yaml::from_str(&content).map_err(|e| format!("Failed to parse {}: {}", path, e))
}

fn write_yaml(path: &str, val: &serde_yaml::Value) -> Result<(), String> {
    let content =
        serde_yaml::to_string(val).map_err(|e| format!("Failed to serialize YAML: {}", e))?;
    fs::write(path, content).map_err(|e| format!("Failed to write {}: {}", path, e))
}

fn model_config_to_yaml(config: &ModelConfig) -> serde_yaml::Value {
    let mut map = serde_yaml::Mapping::new();
    map.insert(y_str("provider"), y_str(&config.provider));
    map.insert(y_str("api_key_env"), y_str(&config.api_key_env));
    if let Some(ref base) = config.base_url_env {
        if !base.is_empty() {
            map.insert(y_str("base_url_env"), y_str(base));
        }
    }
    map.insert(y_str("model_id"), y_str(&config.model_id));
    map.insert(y_str("nickname"), y_str(&config.nickname));
    map.insert(
        y_str("temperature"),
        serde_yaml::Value::Number(serde_yaml::Number::from(config.temperature)),
    );
    map.insert(
        y_str("max_tokens"),
        serde_yaml::Value::Number(serde_yaml::Number::from(config.max_tokens as u64)),
    );
    map.insert(y_str("description"), y_str(&config.description));
    serde_yaml::Value::Mapping(map)
}

fn y_str(s: &str) -> serde_yaml::Value {
    serde_yaml::Value::String(s.to_string())
}

fn validate_model_config(config: &ModelConfig) -> Result<(), String> {
    if config.provider.is_empty() {
        return Err("provider is required".into());
    }
    if !VALID_PROVIDERS.contains(&config.provider.as_str()) {
        return Err(format!(
            "invalid provider '{}', must be one of: {}",
            config.provider,
            VALID_PROVIDERS.join(", ")
        ));
    }
    if config.api_key_env.is_empty() {
        return Err("api_key_env is required".into());
    }
    if config.model_id.is_empty() {
        return Err("model_id is required".into());
    }
    if config.nickname.is_empty() {
        return Err("nickname is required".into());
    }
    if config.provider == "openai_compatible" && config.base_url_env.as_deref().unwrap_or("").is_empty()
    {
        return Err("base_url_env is required for openai_compatible provider".into());
    }
    Ok(())
}

fn get_models_map(
    root: &serde_yaml::Value,
) -> Result<&serde_yaml::Mapping, String> {
    root.get("models")
        .and_then(|m| m.as_mapping())
        .ok_or_else(|| "routing config missing 'models' mapping".to_string())
}

fn get_roles_map(
    root: &serde_yaml::Value,
) -> Result<&serde_yaml::Mapping, String> {
    root.get("roles")
        .and_then(|r| r.as_mapping())
        .ok_or_else(|| "routing config missing 'roles' mapping".to_string())
}

#[tauri::command]
pub fn add_model(
    state: State<AppState>,
    model_ref: String,
    config: ModelConfig,
) -> Result<(), String> {
    validate_model_config(&config)?;

    let path = routing_path(&state.workbench_root);
    let mut root = read_yaml(&path)?;

    let models = root
        .get("models")
        .and_then(|m| m.as_mapping())
        .ok_or("routing config missing 'models' mapping")?;

    if models.contains_key(&y_str(&model_ref)) {
        return Err(format!("model_ref '{}' already exists", model_ref));
    }

    let models_mut = root
        .get_mut("models")
        .and_then(|m| m.as_mapping_mut())
        .ok_or("cannot modify models")?;

    models_mut.insert(y_str(&model_ref), model_config_to_yaml(&config));
    write_yaml(&path, &root)
}

#[tauri::command]
pub fn update_model(
    state: State<AppState>,
    model_ref: String,
    config: ModelConfig,
) -> Result<(), String> {
    validate_model_config(&config)?;

    let path = routing_path(&state.workbench_root);
    let mut root = read_yaml(&path)?;

    let models = root
        .get("models")
        .and_then(|m| m.as_mapping())
        .ok_or("routing config missing 'models' mapping")?;

    if !models.contains_key(&y_str(&model_ref)) {
        return Err(format!("model_ref '{}' not found", model_ref));
    }

    let models_mut = root
        .get_mut("models")
        .and_then(|m| m.as_mapping_mut())
        .ok_or("cannot modify models")?;

    models_mut.insert(y_str(&model_ref), model_config_to_yaml(&config));
    write_yaml(&path, &root)
}

#[tauri::command]
pub fn remove_model(
    state: State<AppState>,
    model_ref: String,
) -> Result<(), String> {
    let path = routing_path(&state.workbench_root);
    let mut root = read_yaml(&path)?;

    let roles = get_roles_map(&root)?;
    for (role_key, role_val) in roles {
        if let Some(ref_val) = role_val.get("model_ref") {
            if ref_val.as_str() == Some(&model_ref) {
                let role_name = role_key.as_str().unwrap_or("?");
                return Err(format!(
                    "cannot remove '{}': still assigned to role '{}'",
                    model_ref, role_name
                ));
            }
        }
    }

    let models_mut = root
        .get_mut("models")
        .and_then(|m| m.as_mapping_mut())
        .ok_or("cannot modify models")?;

    if models_mut.remove(&y_str(&model_ref)).is_none() {
        return Err(format!("model_ref '{}' not found", model_ref));
    }

    write_yaml(&path, &root)
}

#[tauri::command]
pub fn update_role_assignment(
    state: State<AppState>,
    role: String,
    model_ref: String,
) -> Result<(), String> {
    if !VALID_ROLES.contains(&role.as_str()) {
        return Err(format!(
            "invalid role '{}', must be one of: {}",
            role,
            VALID_ROLES.join(", ")
        ));
    }

    let path = routing_path(&state.workbench_root);
    let mut root = read_yaml(&path)?;

    let models = get_models_map(&root)?;
    if !models.contains_key(&y_str(&model_ref)) {
        return Err(format!(
            "model_ref '{}' does not exist in the model registry",
            model_ref
        ));
    }

    let roles_mut = root
        .get_mut("roles")
        .and_then(|r| r.as_mapping_mut())
        .ok_or("cannot modify roles")?;

    if let Some(role_entry) = roles_mut.get_mut(&y_str(&role)) {
        if let Some(map) = role_entry.as_mapping_mut() {
            map.insert(y_str("model_ref"), y_str(&model_ref));
        } else {
            return Err(format!("role '{}' has invalid structure", role));
        }
    } else {
        let mut entry = serde_yaml::Mapping::new();
        entry.insert(y_str("model_ref"), y_str(&model_ref));
        entry.insert(y_str("description"), y_str(""));
        roles_mut.insert(y_str(&role), serde_yaml::Value::Mapping(entry));
    }

    write_yaml(&path, &root)
}

#[tauri::command]
pub fn update_project_model_policy(
    state: State<AppState>,
    project_id: String,
    policy: ProjectModelPolicy,
) -> Result<(), String> {
    let path = project_config_path(&state.workbench_root, &project_id);
    let mut root = read_yaml(&path)?;

    let policy_yaml: serde_yaml::Value = serde_yaml::to_value(&policy)
        .map_err(|e| format!("Failed to convert policy: {}", e))?;

    if let Some(map) = root.as_mapping_mut() {
        map.insert(y_str("model_policy"), policy_yaml);
    } else {
        return Err("project config is not a YAML mapping".into());
    }

    write_yaml(&path, &root)
}
