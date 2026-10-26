#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

struct Backend(Mutex<Option<Child>>);

fn main() {
    tauri::Builder::default()
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent().unwrap().parent().unwrap().to_path_buf();
            let child = Command::new("python")
                .args(["-m", "uvicorn", "assistant.backend.main:app", "--host", "127.0.0.1", "--port", "8788"])
                .current_dir(&root)
                .spawn()
                .ok();
            app.state::<Backend>().0.lock().unwrap().replace(child.unwrap_or_else(|| {
                Command::new("python").args(["-c", "pass"]).spawn().expect("无法启动本地 Python")
            }));
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                if let Some(state) = window.try_state::<Backend>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() { let _ = child.kill(); }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("启动 App 失败");
}
