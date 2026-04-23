use std::net::TcpListener;
use std::sync::Mutex;

use tauri::Manager;
use tauri::State;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

struct ApiState {
    base_url: String,
    _child: Mutex<Option<CommandChild>>,
}

#[tauri::command]
fn api_base_url(state: State<ApiState>) -> String {
    state.base_url.clone()
}

fn find_open_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    let port = listener.local_addr().map_err(|error| error.to_string())?.port();
    drop(listener);
    Ok(port)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let port = find_open_port().map_err(|error| -> Box<dyn std::error::Error> { error.into() })?;
            let base_url = format!("http://127.0.0.1:{port}");

            let sidecar = app
                .shell()
                .sidecar("nfl-prop-api")
                .map_err(|error| -> Box<dyn std::error::Error> { error.into() })?
                .args(["--host", "127.0.0.1", "--port", &port.to_string()]);

            let (_rx, child) = sidecar
                .spawn()
                .map_err(|error| -> Box<dyn std::error::Error> { error.into() })?;

            app.manage(ApiState {
                base_url,
                _child: Mutex::new(Some(child)),
            });

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("NFL Prop Predictor");
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![api_base_url])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
