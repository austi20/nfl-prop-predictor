use std::net::SocketAddr;
use std::net::TcpListener;
use std::net::TcpStream;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::Manager;
use tauri::State;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

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

/// PyInstaller onefile can take 1–2+ minutes to extract and import; the webview can load before HTTP is up.
/// Wait for a successful TCP connect so `invoke("api_base_url")` and the first fetch do not hit a dead port.
fn wait_for_sidecar_tcp(addr: SocketAddr) -> Result<(), String> {
    const ATTEMPTS: u32 = 300;
    const PAUSE: Duration = Duration::from_millis(500);
    eprintln!("[nfl-prop-predictor] waiting for sidecar on {addr} (up to ~{}s)…", ATTEMPTS * PAUSE.as_millis() as u32 / 1000);

    for i in 0..ATTEMPTS {
        if TcpStream::connect(addr).is_ok() {
            eprintln!("[nfl-prop-predictor] sidecar accepting connections on {addr} after {i} attempts");
            return Ok(());
        }
        thread::sleep(PAUSE);
    }

    Err(format!(
        "nfl-prop-api did not open {addr} after ~{timeout}s. Rebuild: desktop/scripts/build-sidecar.ps1, or run: uv run uvicorn api.server:app --host 127.0.0.1 --port <port>",
        timeout = ATTEMPTS * PAUSE.as_millis() as u32 / 1000
    ))
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

            let addr: SocketAddr = format!("127.0.0.1:{port}")
                .parse()
                .map_err(|e: std::net::AddrParseError| -> Box<dyn std::error::Error> { e.into() })?;
            wait_for_sidecar_tcp(addr).map_err(|e| -> Box<dyn std::error::Error> { e.into() })?;

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
