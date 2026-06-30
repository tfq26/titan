use std::io::BufRead;
use std::process::{Command, Stdio};
use std::sync::OnceLock;
use std::thread;
use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, State};

use crate::AppState;

#[derive(Serialize)]
pub struct CommandResult {
    pub stdout: String,
    pub stderr: String,
    pub exit_code: Option<i32>,
}

#[derive(Clone, Serialize)]
pub struct DiscourseLinePayload {
    pub text: String,
    pub stream: String,
}

#[derive(Clone, Serialize)]
pub struct DiscourseCompletePayload {
    pub exit_code: Option<i32>,
}

#[derive(Clone, Serialize)]
pub struct DiscourseStartPayload {
    pub participants: String,
    pub nicknames: String,
    pub request: String,
    pub project: String,
}

#[derive(Clone, Serialize)]
pub struct DiscourseTurnStartPayload {
    pub role: String,
    pub nickname: String,
    pub turn: u32,
}

#[derive(Clone, Serialize)]
pub struct DiscourseTokenPayload {
    pub role: String,
    pub text: String,
}

#[derive(Clone, Serialize)]
pub struct DiscourseTurnEndPayload {
    pub role: String,
    pub text: String,
    pub input_tokens: u64,
    pub output_tokens: u64,
}

#[derive(Clone, Serialize)]
pub struct DiscourseDonePayload {
    pub consensus: bool,
    pub ready_to_queue: bool,
}

static PYTHON: OnceLock<String> = OnceLock::new();

fn python_bin(workbench_root: &str) -> &'static str {
    PYTHON.get_or_init(|| {
        let venv = format!("{}/.venv/bin/python3", workbench_root);
        if std::path::Path::new(&venv).exists() {
            return venv;
        }
        for path in [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ] {
            if std::path::Path::new(path).exists() {
                return path.to_string();
            }
        }
        "python3".to_string()
    })
}

fn run_orchestrator(workbench_root: &str, args: &[&str]) -> Result<CommandResult, String> {
    let output = Command::new(python_bin(workbench_root))
        .arg("-m")
        .arg("orchestrator.run")
        .args(args)
        .current_dir(workbench_root)
        .output()
        .map_err(|e| format!("Failed to run orchestrator: {}", e))?;

    Ok(CommandResult {
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        exit_code: output.status.code(),
    })
}

#[tauri::command]
pub fn run_request(
    state: State<AppState>,
    project_id: String,
    request: String,
) -> Result<CommandResult, String> {
    run_orchestrator(
        &state.workbench_root,
        &["-p", &project_id, "-r", &request],
    )
}

#[tauri::command]
pub fn run_chat(
    state: State<AppState>,
    project_id: String,
    message: String,
    role: Option<String>,
    response_mode: Option<String>,
    chat_context: Option<String>,
) -> Result<CommandResult, String> {
    let role_val = role.unwrap_or_else(|| "worker".to_string());
    let response_mode_val = response_mode.unwrap_or_else(|| "brief".to_string());
    let mut args = vec![
        "-p",
        &project_id,
        "--chat",
        "-r",
        &message,
        "--role",
        &role_val,
        "--response-mode",
        &response_mode_val,
    ];
    if let Some(context) = chat_context.as_deref().filter(|value| !value.trim().is_empty()) {
        args.push("--chat-context");
        args.push(context);
    }
    run_orchestrator(&state.workbench_root, &args)
}

#[tauri::command]
pub fn resume_session(
    state: State<AppState>,
    project_id: String,
    session_id: String,
) -> Result<CommandResult, String> {
    run_orchestrator(
        &state.workbench_root,
        &["-p", &project_id, "-s", &session_id, "--resume"],
    )
}

#[tauri::command]
pub fn run_drift_scan(
    state: State<AppState>,
    project_id: String,
) -> Result<CommandResult, String> {
    run_orchestrator(
        &state.workbench_root,
        &["-p", &project_id, "--scan-drift"],
    )
}

#[tauri::command]
pub fn resume_with_response(
    state: State<AppState>,
    project_id: String,
    session_id: String,
    response: String,
) -> Result<CommandResult, String> {
    run_orchestrator(
        &state.workbench_root,
        &[
            "-p", &project_id,
            "-s", &session_id,
            "--resume",
            "--human-response", &response,
        ],
    )
}

#[tauri::command]
pub fn start_watcher(
    state: State<AppState>,
    project_id: String,
    interval: Option<f64>,
) -> Result<String, String> {
    let interval_str = format!("{}", interval.unwrap_or(5.0));
    let child = Command::new(python_bin(&state.workbench_root))
        .arg("-m")
        .arg("orchestrator.run")
        .args(["-p", &project_id, "--watch", "--watch-interval", &interval_str])
        .current_dir(&state.workbench_root)
        .spawn()
        .map_err(|e| format!("Failed to start watcher: {}", e))?;

    let pid = child.id();
    *state.watcher_pid.lock().unwrap() = Some(pid);
    Ok(format!("Watcher started with PID {} (interval={}s)", pid, interval_str))
}

#[tauri::command]
pub fn stop_watcher(state: State<AppState>) -> Result<String, String> {
    let mut pid_lock = state.watcher_pid.lock().unwrap();
    if let Some(pid) = pid_lock.take() {
        #[cfg(unix)]
        {
            let _ = Command::new("kill")
                .arg(pid.to_string())
                .output();
        }
        #[cfg(not(unix))]
        {
            let _ = Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/F"])
                .output();
        }
        Ok(format!("Watcher PID {} stopped", pid))
    } else {
        Ok("No watcher running".to_string())
    }
}

#[tauri::command]
pub fn run_discourse(
    app: AppHandle,
    state: State<AppState>,
    project_id: String,
    request: String,
    roles: Option<String>,
) -> Result<(), String> {
    let mut args = vec![
        "-p".to_string(),
        project_id,
        "--discourse".to_string(),
        "-r".to_string(),
        request,
        "--json-stream".to_string(),
    ];
    if let Some(r) = roles {
        if !r.trim().is_empty() {
            args.push("--discourse-roles".to_string());
            args.push(r);
        }
    }

    let mut child = Command::new(python_bin(&state.workbench_root))
        .arg("-m")
        .arg("orchestrator.run")
        .args(&args)
        .current_dir(&state.workbench_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn discourse: {}", e))?;

    let stdout = child.stdout.take()
        .ok_or_else(|| "Failed to capture stdout".to_string())?;
    let stderr = child.stderr.take()
        .ok_or_else(|| "Failed to capture stderr".to_string())?;

    thread::spawn(move || {
        // Stream stdout line by line, parsing JSON events
        let reader = std::io::BufReader::new(stdout);
        for line in reader.lines() {
            if let Ok(text) = line {
                if text.trim().starts_with('{') {
                    if let Ok(json) = serde_json::from_str::<Value>(&text) {
                        let event_type = json.get("type").and_then(|v| v.as_str()).unwrap_or("");
                        match event_type {
                            "discourse_start" => {
                                let _ = app.emit("discourse-start", DiscourseStartPayload {
                                    participants: json.get("participants").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                    nicknames: json.get("nicknames").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                    request: json.get("request").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                    project: json.get("project").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                });
                            }
                            "turn_start" => {
                                let role = json.get("role").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let nickname = json.get("nickname").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let turn = json.get("turn").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
                                let _ = app.emit("discourse-turn-start", DiscourseTurnStartPayload {
                                    role, nickname, turn,
                                });
                            }
                            "token" => {
                                let role = json.get("role").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let text = json.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let _ = app.emit("discourse-token", DiscourseTokenPayload {
                                    role, text,
                                });
                            }
                            "turn_end" => {
                                let role = json.get("role").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let text = json.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let input_tokens = json.get("input_tokens").and_then(|v| v.as_u64()).unwrap_or(0);
                                let output_tokens = json.get("output_tokens").and_then(|v| v.as_u64()).unwrap_or(0);
                                let _ = app.emit("discourse-turn-end", DiscourseTurnEndPayload {
                                    role, text, input_tokens, output_tokens,
                                });
                            }
                            "consensus" => {
                                // No separate event needed; handled in discourse_complete
                            }
                            "discourse_complete" => {
                                let consensus = json.get("consensus").and_then(|v| v.as_bool()).unwrap_or(false);
                                let ready = json.get("ready_to_queue").and_then(|v| v.as_bool()).unwrap_or(false);
                                let _ = app.emit("discourse-done", DiscourseDonePayload {
                                    consensus,
                                    ready_to_queue: ready,
                                });
                            }
                            _ => {
                                // Unknown JSON event — fall through to raw line
                                let _ = app.emit("discourse-line", DiscourseLinePayload {
                                    text,
                                    stream: "stdout".to_string(),
                                });
                            }
                        }
                        continue;
                    }
                }
                // Non-JSON line — emit as raw text
                let _ = app.emit("discourse-line", DiscourseLinePayload {
                    text,
                    stream: "stdout".to_string(),
                });
            }
        }

        // Stream remaining stderr as raw lines
        let reader = std::io::BufReader::new(stderr);
        for line in reader.lines() {
            if let Ok(text) = line {
                let _ = app.emit("discourse-line", DiscourseLinePayload {
                    text,
                    stream: "stderr".to_string(),
                });
            }
        }

        // Wait for process
        let exit_code = child.wait().ok().and_then(|s| s.code());
        let _ = app.emit("discourse-complete", DiscourseCompletePayload { exit_code });
    });

    Ok(())
}
