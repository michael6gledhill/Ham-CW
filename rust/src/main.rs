// ham-cw: Iambic CW keyer with axum web interface.
//
// Reads SPDT switches and iambic paddles via rppal GPIO,
// generates accurate Morse code audio via cpal/ALSA,
// and provides a web-based settings interface.

mod audio;
mod gpio;
mod morse;
mod settings;

use audio::AudioEngine;
use gpio::{GpioDetector, GpioManager};
use morse::{text_to_elements, Element, Keyer, KeyerState, ToneElement};
use settings::{Settings, AUTO_DETECT_PINS, GPIO_PINS};

use axum::{
    extract::State as AxState,
    http::StatusCode,
    response::{Html, Json},
    routing::{get, post},
    Router,
};
use serde_json::{json, Value};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, RwLock};
use std::time::Instant;
use tower_http::services::ServeDir;

// --------------------------------------------------------------------------
//  Shared application state
// --------------------------------------------------------------------------

struct KeyerStatus {
    key_down: bool,
    dit: bool,
    dah: bool,
    mode: String,
    sending: bool,
}

struct AppInner {
    settings: Settings,
    gpio: Mutex<GpioManager>,
    audio: Mutex<AudioEngine>,
    detector: GpioDetector,
    status: RwLock<KeyerStatus>,
    send_queue: Mutex<Vec<ToneElement>>,
    config_mode: AtomicBool,
    config_awaiting: RwLock<Option<String>>,
    shutdown: AtomicBool,
    #[allow(dead_code)]
    base_dir: PathBuf,
}

type AppState = Arc<AppInner>;

// --------------------------------------------------------------------------
//  Keyer loop — precision-timed with spin-wait at deadlines
// --------------------------------------------------------------------------

fn keyer_loop(app: AppState) {
    let mut keyer = Keyer::new(20);
    let mut sq_action: Option<bool> = None;
    let mut sq_end = 0.0f64;

    let cfg = app.settings.get();
    let mut wpm = cfg.wpm;
    let mut _freq = cfg.frequency;
    keyer.update(wpm);

    let start = Instant::now();
    let mono = || start.elapsed().as_secs_f64();

    let mut cfg_next = mono() + 0.1;

    loop {
        if app.shutdown.load(Ordering::Relaxed) {
            break;
        }

        let now = mono();

        // Refresh config periodically
        if now >= cfg_next {
            let cfg = app.settings.get();
            if cfg.wpm != wpm {
                wpm = cfg.wpm;
                keyer.update(wpm);
            }
            _freq = cfg.frequency;
            cfg_next = now + 0.1;
        }

        // Read paddles
        let (dit, dah) = {
            let gpio = app.gpio.lock().unwrap();
            gpio.read_paddles()
        };
        {
            let mut st = app.status.write().unwrap();
            st.dit = dit;
            st.dah = dah;
        }

        // Paddle press cancels text send
        if dit || dah {
            let mut sq = app.send_queue.lock().unwrap();
            if !sq.is_empty() {
                sq.clear();
                sq_action = None;
            }
        }

        // Process send queue
        if sq_action.is_some() && now >= sq_end {
            sq_action = None;
        }
        if sq_action.is_none() {
            let mut sq = app.send_queue.lock().unwrap();
            if !sq.is_empty() {
                let el = sq.remove(0);
                sq_action = Some(el.on);
                sq_end = now + el.duration;
            }
        }

        let sending = sq_action.is_some() || !app.send_queue.lock().unwrap().is_empty();

        // Determine key state
        let key_down = if let Some(on) = sq_action {
            on
        } else {
            keyer.tick(now, dit, dah)
        };

        // Drive speaker + audio on transitions
        let prev_key_down = app.status.read().unwrap().key_down;
        if key_down != prev_key_down {
            let mut st = app.status.write().unwrap();
            st.key_down = key_down;
            st.sending = sending;
            drop(st);

            let audio = app.audio.lock().unwrap();
            let mut gpio = app.gpio.lock().unwrap();
            if key_down {
                gpio.speaker_on();
                audio.key_on();
            } else {
                gpio.speaker_off();
                audio.key_off();
            }
        } else {
            app.status.write().unwrap().sending = sending;
        }

        // Precision wait for next deadline
        if keyer.state == KeyerState::Sending {
            let deadline = keyer.deadline;
            loop {
                let remain = deadline - mono();
                if remain <= 0.0005 {
                    break;
                }
                // Poll paddles during element for Mode-B memory
                let (d, h) = app.gpio.lock().unwrap().read_paddles();
                {
                    let mut st = app.status.write().unwrap();
                    st.dit = d;
                    st.dah = h;
                }
                if keyer.element == Some(Element::Dit) && h {
                    keyer.mem = Some(Element::Dah);
                } else if keyer.element == Some(Element::Dah) && d {
                    keyer.mem = Some(Element::Dit);
                }
                if remain > 0.003 {
                    std::thread::sleep(std::time::Duration::from_millis(1));
                }
            }
            while mono() < deadline {}
        } else if keyer.state == KeyerState::Spacing {
            let deadline = keyer.deadline;
            let remain = deadline - mono();
            if remain > 0.002 {
                std::thread::sleep(std::time::Duration::from_secs_f64(remain - 0.001));
            }
            while mono() < deadline {}
        } else if sq_action.is_some() {
            let remain = sq_end - mono();
            if remain > 0.002 {
                std::thread::sleep(std::time::Duration::from_secs_f64(remain - 0.001));
            }
            while mono() < sq_end {}
        } else {
            // IDLE — poll paddles at ~1ms
            std::thread::sleep(std::time::Duration::from_millis(1));
        }
    }
}

// --------------------------------------------------------------------------
//  Switch polling thread (50 Hz)
// --------------------------------------------------------------------------

fn switch_poll_loop(app: AppState) {
    let mut prev_sw: std::collections::HashMap<String, bool> = std::collections::HashMap::new();

    loop {
        if app.shutdown.load(Ordering::Relaxed) {
            break;
        }

        if app.config_mode.load(Ordering::Relaxed) {
            std::thread::sleep(std::time::Duration::from_millis(100));
            continue;
        }

        // Settings toggle
        let settings_pressed = app.gpio.lock().unwrap().read_pin("pin_settings");
        {
            let mut st = app.status.write().unwrap();
            st.mode = if settings_pressed {
                "settings".to_string()
            } else {
                "transmit".to_string()
            };
        }

        // Edge-detected adjustments
        for (role, param, step) in &[
            ("pin_freq_up", "frequency", 10i32),
            ("pin_freq_down", "frequency", -10),
            ("pin_speed_up", "wpm", 1),
            ("pin_speed_down", "wpm", -1),
        ] {
            let cur = app.gpio.lock().unwrap().read_pin(role);
            let prev = prev_sw.get(*role).copied().unwrap_or(false);
            if cur && !prev {
                if let Some(val) = app.settings.adjust(param, *step) {
                    if *param == "frequency" {
                        app.audio.lock().unwrap().set_frequency(val);
                    }
                }
            }
            prev_sw.insert(role.to_string(), cur);
        }

        std::thread::sleep(std::time::Duration::from_millis(20));
    }
}

// --------------------------------------------------------------------------
//  Detection helpers
// --------------------------------------------------------------------------

fn start_detection(app: &AppState, role: &str) {
    app.config_mode.store(true, Ordering::Relaxed);
    *app.config_awaiting.write().unwrap() = Some(role.to_string());

    app.gpio.lock().unwrap().close();

    let cfg = app.settings.get();
    let mut exclude = Vec::new();
    for r in GPIO_PINS {
        if *r != role {
            let pin = cfg.get_pin(r);
            if pin > 0 {
                exclude.push(pin as u8);
            }
        }
    }

    app.detector.start(role, &exclude);
}

fn stop_detection(app: &AppState) {
    app.detector.stop();
    app.config_mode.store(false, Ordering::Relaxed);
    *app.config_awaiting.write().unwrap() = None;
    let cfg = app.settings.get();
    app.gpio.lock().unwrap().setup(&cfg);
}

fn confirm_detection(app: &AppState, pin: i32, role: &str) {
    app.detector.stop();
    app.settings.update(&json!({ role: pin }));
    app.config_mode.store(false, Ordering::Relaxed);
    *app.config_awaiting.write().unwrap() = None;
    let cfg = app.settings.get();
    app.gpio.lock().unwrap().setup(&cfg);
}

// --------------------------------------------------------------------------
//  HTML template (embedded at compile time)
// --------------------------------------------------------------------------

const INDEX_HTML: &str = include_str!("../static_assets/index.html");

// --------------------------------------------------------------------------
//  Route handlers
// --------------------------------------------------------------------------

async fn index_handler() -> Html<&'static str> {
    Html(INDEX_HTML)
}

async fn get_settings_handler(AxState(app): AxState<AppState>) -> Json<Value> {
    Json(serde_json::to_value(app.settings.get()).unwrap())
}

async fn update_settings_handler(
    AxState(app): AxState<AppState>,
    Json(data): Json<Value>,
) -> Json<Value> {
    let old_cfg = app.settings.get();
    app.settings.update(&data);
    let cfg = app.settings.get();
    app.audio.lock().unwrap().set_frequency(cfg.frequency);

    let pins_changed = GPIO_PINS
        .iter()
        .any(|r| cfg.get_pin(r) != old_cfg.get_pin(r));
    if pins_changed && !app.config_mode.load(Ordering::Relaxed) {
        app.gpio.lock().unwrap().setup(&cfg);
    }

    Json(json!({"ok": true}))
}

async fn save_settings_handler(AxState(app): AxState<AppState>) -> Json<Value> {
    app.settings.save();
    Json(json!({"ok": true}))
}

async fn gpio_status_handler(AxState(app): AxState<AppState>) -> Json<Value> {
    let st = app.status.read().unwrap();
    Json(json!({
        "mode": st.mode,
        "dit": st.dit,
        "dah": st.dah,
        "key_down": st.key_down,
        "sending": st.sending,
    }))
}

async fn start_detection_handler(
    AxState(app): AxState<AppState>,
    Json(data): Json<Value>,
) -> Result<Json<Value>, StatusCode> {
    let role = data.get("role").and_then(|v| v.as_str()).unwrap_or("");
    if !AUTO_DETECT_PINS.contains(&role) {
        return Err(StatusCode::BAD_REQUEST);
    }
    start_detection(&app, role);
    Ok(Json(json!({"status": "detecting", "role": role})))
}

async fn detection_status_handler(AxState(app): AxState<AppState>) -> Json<Value> {
    let status = app.detector.get_status();
    let cfg = app.settings.get();
    let mut assigned = serde_json::Map::new();
    for r in GPIO_PINS {
        let pin = cfg.get_pin(r);
        if pin > 0 {
            assigned.insert(pin.to_string(), json!(r));
        }
    }
    Json(json!({
        "detecting": status.detecting,
        "detected_pins": status.detected_pins,
        "timed_out": status.timed_out,
        "error": status.error,
        "role": status.role,
        "elapsed": (status.elapsed * 10.0).round() / 10.0,
        "assigned": assigned,
    }))
}

async fn stop_detection_handler(AxState(app): AxState<AppState>) -> Json<Value> {
    stop_detection(&app);
    Json(json!({"status": "stopped"}))
}

async fn confirm_gpio_handler(
    AxState(app): AxState<AppState>,
    Json(data): Json<Value>,
) -> Result<Json<Value>, StatusCode> {
    let pin = data.get("pin").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    let role = data.get("role").and_then(|v| v.as_str()).unwrap_or("");
    if !AUTO_DETECT_PINS.contains(&role) || !(0..=27).contains(&pin) {
        return Err(StatusCode::BAD_REQUEST);
    }
    confirm_detection(&app, pin, role);
    Ok(Json(json!({"ok": true, "pin": pin, "role": role})))
}

async fn adjust_handler(
    AxState(app): AxState<AppState>,
    Json(data): Json<Value>,
) -> Result<Json<Value>, StatusCode> {
    let param = data.get("param").and_then(|v| v.as_str()).unwrap_or("");
    let step = data.get("step").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    if settings::limits(param).is_none() || step == 0 {
        return Err(StatusCode::BAD_REQUEST);
    }
    if let Some(val) = app.settings.adjust(param, step) {
        if param == "frequency" {
            app.audio.lock().unwrap().set_frequency(val);
        }
        Ok(Json(json!({"ok": true, "value": val})))
    } else {
        Err(StatusCode::BAD_REQUEST)
    }
}

async fn send_handler(
    AxState(app): AxState<AppState>,
    Json(data): Json<Value>,
) -> Json<Value> {
    let text = data
        .get("text")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if !text.is_empty() {
        let cfg = app.settings.get();
        let els = text_to_elements(&text, cfg.wpm);
        let mut sq = app.send_queue.lock().unwrap();
        sq.clear();
        sq.extend(els);
    }
    Json(json!({"ok": true}))
}

async fn stop_handler(AxState(app): AxState<AppState>) -> Json<Value> {
    app.send_queue.lock().unwrap().clear();
    Json(json!({"ok": true}))
}

async fn test_handler(AxState(app): AxState<AppState>) -> Json<Value> {
    let mut sq = app.send_queue.lock().unwrap();
    sq.clear();
    sq.push(ToneElement {
        on: true,
        duration: 0.5,
    });
    Json(json!({"ok": true}))
}

// --------------------------------------------------------------------------
//  Entry point
// --------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    let base_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));

    let settings = Settings::new(&base_dir);
    settings.load();
    let cfg = settings.get();

    let mut gpio = GpioManager::new();
    gpio.setup(&cfg);

    let mut audio = AudioEngine::new();
    audio.set_frequency(cfg.frequency);
    audio.start();

    let app: AppState = Arc::new(AppInner {
        settings,
        gpio: Mutex::new(gpio),
        audio: Mutex::new(audio),
        detector: GpioDetector::new(),
        status: RwLock::new(KeyerStatus {
            key_down: false,
            dit: false,
            dah: false,
            mode: "transmit".to_string(),
            sending: false,
        }),
        send_queue: Mutex::new(Vec::new()),
        config_mode: AtomicBool::new(false),
        config_awaiting: RwLock::new(None),
        shutdown: AtomicBool::new(false),
        base_dir: base_dir.clone(),
    });

    // Keyer thread
    let app_keyer = Arc::clone(&app);
    std::thread::spawn(move || keyer_loop(app_keyer));

    // Switch poll thread
    let app_switch = Arc::clone(&app);
    std::thread::spawn(move || switch_poll_loop(app_switch));

    // Shutdown handler
    let app_shutdown = Arc::clone(&app);
    tokio::spawn(async move {
        tokio::signal::ctrl_c().await.ok();
        app_shutdown.shutdown.store(true, Ordering::Relaxed);
        println!("morse-keyer: shutting down...");
        std::process::exit(0);
    });

    // Static file service
    let static_dir = base_dir.join("static");

    let router = Router::new()
        .route("/", get(index_handler))
        .route("/settings", get(get_settings_handler))
        .route("/settings", post(update_settings_handler))
        .route("/save-settings", post(save_settings_handler))
        .route("/gpio-status", get(gpio_status_handler))
        .route("/api/start-detection", post(start_detection_handler))
        .route("/api/detection-status", get(detection_status_handler))
        .route("/api/stop-detection", post(stop_detection_handler))
        .route("/api/confirm-gpio", post(confirm_gpio_handler))
        .route("/api/adjust", post(adjust_handler))
        .route("/api/send", post(send_handler))
        .route("/api/stop", post(stop_handler))
        .route("/api/test", post(test_handler))
        .nest_service("/static", ServeDir::new(static_dir))
        .with_state(app);

    let addr = SocketAddr::from(([0, 0, 0, 0], 80));
    println!("morse-keyer: listening on http://{addr}");

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("failed to bind port 80");

    axum::serve(listener, router)
        .await
        .expect("server error");
}
