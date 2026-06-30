mod commands;

use std::sync::Mutex;
use tauri::Manager;

pub struct AppState {
    pub watcher_pid: Mutex<Option<u32>>,
    pub workbench_root: String,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let workbench_root =
        std::env::var("WORKBENCH_ROOT").unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_default();
            format!("{}/Projects/workbench-vault", home)
        });

    tauri::Builder::default()
        .setup(|app| {
            commands::system::load_env_from_secrets(&workbench_root);
            app.manage(AppState {
                watcher_pid: Mutex::new(None),
                workbench_root,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::files::read_file,
            commands::files::list_dir,
            commands::files::read_registry,
            commands::files::add_project,
            commands::files::read_project_config,
            commands::files::read_routing,
            commands::files::read_queue,
            commands::files::read_task,
            commands::files::save_chat_history,
            commands::files::load_chat_history,
            commands::files::start_new_chat,
            commands::files::list_chat_histories,
            commands::files::update_task,
            commands::files::delete_task,
            commands::cli::run_request,
            commands::cli::run_chat,
            commands::cli::resume_session,
            commands::cli::run_drift_scan,
            commands::cli::start_watcher,
            commands::cli::stop_watcher,
            commands::cli::resume_with_response,
            commands::cli::run_discourse,
            commands::system::check_env_vars,
            commands::system::open_path,
            commands::system::pick_folder,
            commands::system::get_workbench_root,
            commands::system::get_trace_config,
            commands::system::check_secrets_file,
            commands::system::load_secrets_file,
            commands::server::get_server_config_path,
            commands::server::load_server_config,
            commands::server::save_server_config,
            commands::server::test_server_connection,
            commands::server::sync_server_now,
            commands::server::backup_vault_snapshot,
            commands::models::add_model,
            commands::models::update_model,
            commands::models::remove_model,
            commands::models::update_role_assignment,
            commands::models::update_project_model_policy,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
