//! ham-cw — Minimal CW iambic keyer for Raspberry Pi Zero
//!
//! Wiring (BCM numbers):
//!   GPIO 12  ← DIT paddle (active-high, internal pull-down)
//!   GPIO 13  ← DAH paddle (active-high, internal pull-down)
//!   GPIO  2  ← TX switch  (active-high ⇒ transmit enabled)
//!   GPIO  3  ← SPK switch
//!   GPIO 18  → PTT output (high = transmit)
//!
//! Usage:  ham-cw [WPM]   e.g.  ham-cw 20
//! Web UI: http://<pi-ip>:8080

use rppal::gpio::{Gpio, InputPin, OutputPin};
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, SyncSender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use std::{env, process, thread};

// Global shutdown flag written only by signal handlers
static SHUTDOWN: AtomicBool = AtomicBool::new(false);

extern "C" fn on_signal(_: libc::c_int) {
    SHUTDOWN.store(true, Ordering::SeqCst);
}

// ─── Default configuration ────────────────────────────────────────────────────

const DEFAULT_WPM:    u32 = 20;    // words per minute
const DEFAULT_FREQ:   u32 = 700;   // sidetone Hz
const DEFAULT_WEIGHT: u32 = 300;   // dash length = weight/100 × dit (300 = 3×)
const DEFAULT_VOL:    u32 = 70;    // system volume 0–100

const DEFAULT_PIN_DIT:  u8 = 12;
const DEFAULT_PIN_DAH:  u8 = 13;
const DEFAULT_PIN_TX:   u8 = 2;
const DEFAULT_PIN_SPK:  u8 = 3;
const DEFAULT_PIN_PTT:  u8 = 18;

#[cfg(feature = "sidetone")]
const SAMPLE_RATE:   u32 = 44_100;
#[cfg(feature = "sidetone")]
const PERIOD_FRAMES: u32 = 256;   // ~5.8 ms latency at 44100 Hz

/// Runtime-adjustable settings, shared between HTTP thread and keyer loop.
#[derive(Clone)]
struct Config {
    wpm:    u32,  // 5–60
    freq:   u32,  // sidetone Hz, 200–2000
    weight: u32,  // dash/dit ratio ×100, 200–500 (300 = standard 3:1)
    volume: u32,  // system master volume 0–100
    // GPIO BCM pin numbers
    pin_dit: u8,
    pin_dah: u8,
    pin_tx:  u8,
    pin_spk: u8,
    pin_ptt: u8,
}

impl Config {
    fn default() -> Self {
        Config {
            wpm: DEFAULT_WPM, freq: DEFAULT_FREQ, weight: DEFAULT_WEIGHT, volume: DEFAULT_VOL,
            pin_dit: DEFAULT_PIN_DIT, pin_dah: DEFAULT_PIN_DAH,
            pin_tx:  DEFAULT_PIN_TX,  pin_spk: DEFAULT_PIN_SPK, pin_ptt: DEFAULT_PIN_PTT,
        }
    }
    fn dit_dur(&self) -> Duration {
        Duration::from_millis(1200 / self.wpm as u64)
    }
    fn dah_dur(&self) -> Duration {
        let dit_ms = 1200 / self.wpm as u64;
        Duration::from_millis(dit_ms * self.weight as u64 / 100)
    }
    fn to_json(&self) -> String {
        format!(
            "{\"wpm\":{},\"freq\":{},\"weight\":{},\"volume\":{},\"pin_dit\":{},\"pin_dah\":{},\"pin_tx\":{},\"pin_spk\":{},\"pin_ptt\":{}}",
            self.wpm, self.freq, self.weight, self.volume,
            self.pin_dit, self.pin_dah, self.pin_tx, self.pin_spk, self.pin_ptt
        )
    }
}



// ─── Timing helpers ───────────────────────────────────────────────────────────

fn dit_dur(wpm: u32) -> Duration {
    Duration::from_millis(1200 / wpm as u64)
}

/// Apply volume to the Pi's ALSA Master control (0–100).
fn set_system_volume(vol: u32) {
    let v = vol.min(100);
    process::Command::new("amixer")
        .args(["sset", "Master", &format!("{v}%")])
        .stdout(process::Stdio::null())
        .stderr(process::Stdio::null())
        .spawn()
        .ok();
}

// ─── Iambic Mode-B keyer state machine ───────────────────────────────────────
//
// Mode B: at the END of each element the paddles are re-sampled, so squeezing
// and releasing just before the element finishes still schedules one more
// opposite element — the classic "Curtis Mode B" behaviour.

#[derive(Clone, Copy, PartialEq)]
enum Element { Dit, Dah }

#[derive(Clone, Copy, PartialEq)]
enum Phase { Idle, Sending(Element), Spacing }

struct Keyer {
    phase:   Phase,
    last:    Option<Element>,
    dit_mem: bool,
    dah_mem: bool,
    timer:   Instant,
    unit:    Duration,  // pub so keyer loop can update WPM live
}

impl Keyer {
    fn new(wpm: u32) -> Self {
        Keyer {
            phase:   Phase::Idle,
            last:    None,
            dit_mem: false,
            dah_mem: false,
            timer:   Instant::now(),
            unit:    dit_dur(wpm),
        }
    }

    /// Call every ~1 ms with current paddle states.
    /// Returns `true` while the RF key should be held down.
    fn tick(&mut self, dit_dn: bool, dah_dn: bool) -> bool {
        // Accumulate memory any time a paddle is pressed
        if dit_dn { self.dit_mem = true; }
        if dah_dn { self.dah_mem = true; }

        match self.phase {
            Phase::Idle => {
                if let Some(el) = self.choose(dit_dn, dah_dn) {
                    self.begin(el);
                    true
                } else {
                    false
                }
            }

            Phase::Sending(el) => {
                let dur = match el {
                    Element::Dit => self.unit,
                    Element::Dah => self.unit * 3,
                };
                if self.timer.elapsed() >= dur {
                    // Mode B final sample
                    if dit_dn { self.dit_mem = true; }
                    if dah_dn { self.dah_mem = true; }
                    self.last  = Some(el);
                    self.phase = Phase::Spacing;
                    self.timer = Instant::now();
                    false // inter-element space starts
                } else {
                    true // still sending
                }
            }

            Phase::Spacing => {
                if self.timer.elapsed() >= self.unit {
                    if let Some(el) = self.choose(dit_dn, dah_dn) {
                        self.begin(el);
                        true
                    } else {
                        self.phase = Phase::Idle;
                        self.last  = None;
                        false
                    }
                } else {
                    false
                }
            }
        }
    }

    /// Pick the next element from memory + live paddle state.
    fn choose(&mut self, dit_dn: bool, dah_dn: bool) -> Option<Element> {
        let want_dit = self.dit_mem || dit_dn;
        let want_dah = self.dah_mem || dah_dn;
        // Clear memories for what we're about to use
        if want_dit { self.dit_mem = false; }
        if want_dah { self.dah_mem = false; }

        match (want_dit, want_dah) {
            (false, false) => None,
            (true, false)  => Some(Element::Dit),
            (false, true)  => Some(Element::Dah),
            // Squeeze: alternate opposite of last element
            (true, true) => Some(match self.last {
                None | Some(Element::Dah) => Element::Dit,
                Some(Element::Dit)         => Element::Dah,
            }),
        }
    }

    fn begin(&mut self, el: Element) {
        self.phase = Phase::Sending(el);
        self.timer = Instant::now();
    }
}

// ─── ALSA sidetone thread ─────────────────────────────────────────────────────

#[cfg(feature = "sidetone")]
fn run_sidetone(keyed: Arc<AtomicBool>, cfg: Arc<Mutex<Config>>) {
    use alsa::pcm::{Access, Format, HwParams, PCM};
    use alsa::{Direction, ValueOr};

    let pcm = match PCM::new("default", Direction::Playback, false) {
        Ok(p)  => p,
        Err(e) => {
            eprintln!("ham-cw: audio init failed ({e}) – no sidetone");
            return;
        }
    };

    let setup = || -> alsa::Result<()> {
        let hwp = HwParams::any(&pcm)?;
        hwp.set_channels(1)?;
        hwp.set_rate(SAMPLE_RATE, ValueOr::Nearest)?;
        hwp.set_format(Format::s16())?;
        hwp.set_access(Access::RWInterleaved)?;
        hwp.set_period_size(PERIOD_FRAMES as i64, ValueOr::Nearest)?;
        hwp.set_buffer_size(PERIOD_FRAMES as i64 * 4)?;
        pcm.hw_params(&hwp)?;
        pcm.start()
    };

    if let Err(e) = setup() {
        eprintln!("ham-cw: audio setup failed ({e}) – no sidetone");
        return;
    }

    let io = match pcm.io_i16() {
        Ok(io) => io,
        Err(e) => {
            eprintln!("ham-cw: audio io failed ({e}) – no sidetone");
            return;
        }
    };

    let mut buf = vec![0i16; PERIOD_FRAMES as usize];
    let mut phase: f32 = 0.0;
    let mut last_freq: u32 = 0;
    let mut phase_step: f32 = 0.0;

    loop {
        let (on, freq, vol) = {
            let c = cfg.lock().unwrap();
            (keyed.load(Ordering::Relaxed), c.freq, c.volume)
        };
        // Recompute phase_step only when freq changes
        if freq != last_freq {
            phase_step = 2.0 * std::f32::consts::PI * freq as f32 / SAMPLE_RATE as f32;
            last_freq  = freq;
        }
        let amplitude = vol as f32 / 100.0;
        for s in &mut buf {
            *s = if on {
                let v = (phase.sin() * 32_767.0 * amplitude) as i16;
                phase += phase_step;
                if phase >= std::f32::consts::TAU { phase -= std::f32::consts::TAU; }
                v
            } else {
                0
            };
        }
        if let Err(e) = io.writei(&buf) {
            pcm.try_recover(e, true).ok();
        }
    }
}

// ─── Text → Morse ─────────────────────────────────────────────────────────────

fn char_to_morse(c: char) -> Option<&'static str> {
    match c.to_ascii_uppercase() {
        'A' => Some(".-"),    'B' => Some("-..."),  'C' => Some("-.-."),
        'D' => Some("-.."),   'E' => Some("."),      'F' => Some("..-."),
        'G' => Some("--."),   'H' => Some("...."),   'I' => Some(".."),
        'J' => Some(".---"),  'K' => Some("-.-"),    'L' => Some(".-.."),
        'M' => Some("--"),    'N' => Some("-."),     'O' => Some("---"),
        'P' => Some(".--."),  'Q' => Some("--.-"),   'R' => Some(".-."),
        'S' => Some("..."),   'T' => Some("-"),      'U' => Some("..-"),
        'V' => Some("...-"),  'W' => Some(".--"),    'X' => Some("-..-"),
        'Y' => Some("-.--"),  'Z' => Some("--.."),
        '0' => Some("-----"), '1' => Some(".----"),  '2' => Some("..---"),
        '3' => Some("...--"), '4' => Some("....-"),  '5' => Some("....."),
        '6' => Some("-...."), '7' => Some("--..."),  '8' => Some("---.."),
        '9' => Some("----."),
        '.' => Some(".-.-.-"), ',' => Some("--..--"), '?' => Some("..--.."),
        '/' => Some("-..-.."),  ' ' => Some(" "),
        _ => None,
    }
}

/// Send a text string as CW elements via PTT + GPIO.
/// Blocks until the string is fully sent.
fn send_text(text: &str, ptt: &mut OutputPin, cfg: &Config, key_flag: &Arc<AtomicBool>) {
    let unit    = cfg.dit_dur();
    let dah     = cfg.dah_dur();
    let char_sp = unit * 3; // space between letters
    let word_sp = unit * 7; // space between words

    for ch in text.chars() {
        if ch == ' ' {
            thread::sleep(word_sp);
            continue;
        }
        if let Some(morse) = char_to_morse(ch) {
            for (i, sym) in morse.chars().enumerate() {
                let on_dur = if sym == '-' { dah } else { unit };
                ptt.set_high();
                key_flag.store(true, Ordering::Relaxed);
                thread::sleep(on_dur);
                ptt.set_low();
                key_flag.store(false, Ordering::Relaxed);
                // inter-element space (skip after last element)
                if i + 1 < morse.len() {
                    thread::sleep(unit);
                }
            }
            thread::sleep(char_sp);
        }
    }
}

// ─── Minimal HTTP server ──────────────────────────────────────────────────────

// Embedded at compile time — edit src/index.html, then rebuild.
const HTML: &str = include_str!("index.html");
const UPDATE_SH: &str = include_str!("../update.sh");

/// Parse JSON config body — no crate needed.
/// Accepts any subset of {"wpm":N,"freq":N,"weight":N,"volume":N}.
fn parse_config_json(s: &str, base: &Config) -> Config {
    fn extract(s: &str, key: &str) -> Option<u32> {
        let idx = s.find(key)?;
        let rest = &s[idx + key.len()..];
        let colon = rest.find(':')? + 1;
        let digits = rest[colon..].trim_start();
        let end = digits.find(|c: char| !c.is_ascii_digit()).unwrap_or(digits.len());
        digits[..end].parse().ok()
    }
    fn pin(s: &str, key: &str, cur: u8) -> u8 {
        extract(s, key).map(|v| v.min(27) as u8).unwrap_or(cur)
    }
    Config {
        wpm:    extract(s, "\"wpm\"").map(|v| v.max(5).min(60)).unwrap_or(base.wpm),
        freq:   extract(s, "\"freq\"").map(|v| v.max(200).min(2000)).unwrap_or(base.freq),
        weight: extract(s, "\"weight\"").map(|v| v.max(200).min(500)).unwrap_or(base.weight),
        volume: extract(s, "\"volume\"").map(|v| v.min(100)).unwrap_or(base.volume),
        pin_dit: pin(s, "\"pin_dit\"", base.pin_dit),
        pin_dah: pin(s, "\"pin_dah\"", base.pin_dah),
        pin_tx:  pin(s, "\"pin_tx\"",  base.pin_tx),
        pin_spk: pin(s, "\"pin_spk\"", base.pin_spk),
        pin_ptt: pin(s, "\"pin_ptt\"", base.pin_ptt),
    }
}

fn http_respond(mut stream: TcpStream, status: &str, body: &str, ctype: &str) {
    let resp = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    stream.write_all(resp.as_bytes()).ok();
}

fn handle_connection(stream: TcpStream, tx: &SyncSender<String>, cfg_mtx: &Arc<Mutex<Config>>) {
    let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));

    let mut req_line = String::new();
    if reader.read_line(&mut req_line).is_err() { return; }
    let req_line = req_line.trim().to_string();

    let mut content_length: usize = 0;
    loop {
        let mut hdr = String::new();
        if reader.read_line(&mut hdr).is_err() { break; }
        let hdr = hdr.trim();
        if hdr.is_empty() { break; }
        if hdr.to_ascii_lowercase().starts_with("content-length:") {
            content_length = hdr[15..].trim().parse().unwrap_or(0);
        }
    }

    const MAX_BODY: usize = 512;
    if content_length > MAX_BODY {
        http_respond(stream, "413 Payload Too Large", "too large", "text/plain");
        return;
    }

    // GET /update — serve the self-update shell script
    if req_line.starts_with("GET /update") {
        http_respond(stream, "200 OK", UPDATE_SH, "text/x-shellscript; charset=utf-8");
        return;
    }

    // GET /config — return current settings as JSON
    if req_line.starts_with("GET /config") {
        let json = cfg_mtx.lock().unwrap().to_json();
        http_respond(stream, "200 OK", &json, "application/json");
        return;
    }

    // GET / — serve the settings page
    if req_line.starts_with("GET /") {
        http_respond(stream, "200 OK", HTML, "text/html; charset=utf-8");
        return;
    }

    // POST /config — update settings
    if req_line.starts_with("POST /config") {
        use std::io::Read;
        let mut body = vec![0u8; content_length];
        if reader.get_mut().read_exact(&mut body).is_err() {
            http_respond(stream, "400 Bad Request", "read error", "text/plain");
            return;
        }
        let new_cfg = {
            let base = cfg_mtx.lock().unwrap().clone();
            parse_config_json(&String::from_utf8_lossy(&body), &base)
        };
        let vol = new_cfg.volume;
        let json = new_cfg.to_json();
        *cfg_mtx.lock().unwrap() = new_cfg;
        set_system_volume(vol);
        http_respond(stream, "200 OK", &json, "application/json");
        return;
    }

    // POST /send — queue plain-text for CW transmission
    if req_line.starts_with("POST /send") {
        use std::io::Read;
        let mut body = vec![0u8; content_length];
        if reader.get_mut().read_exact(&mut body).is_err() {
            http_respond(stream, "400 Bad Request", "read error", "text/plain");
            return;
        }
        let text = String::from_utf8_lossy(&body).trim().to_string();
        if text.is_empty() {
            http_respond(stream, "400 Bad Request", "empty text", "text/plain");
            return;
        }
        match tx.try_send(text) {
            Ok(_) => http_respond(stream, "200 OK", "queued", "text/plain"),
            Err(_) => http_respond(stream, "503 Service Unavailable", "busy", "text/plain"),
        }
        return;
    }

    http_respond(stream, "404 Not Found", "not found", "text/plain");
}

fn run_http_server(tx: SyncSender<String>, cfg_mtx: Arc<Mutex<Config>>) {
    let listener = TcpListener::bind("0.0.0.0:8080").expect("cannot bind :8080");
    println!("ham-cw web UI: http://0.0.0.0:8080");
    for stream in listener.incoming() {
        if let Ok(s) = stream {
            let tx2  = tx.clone();
            let cfg2 = cfg_mtx.clone();
            thread::spawn(move || handle_connection(s, &tx2, &cfg2));
        }
    }
}

// ─── Main ─────────────────────────────────────────────────────────────────────

fn main() {
    let args: Vec<String> = env::args().collect();

    let wpm: u32 = args.get(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_WPM)
        .max(5)
        .min(60);

    println!("ham-cw starting — {DEFAULT_WPM} WPM, {DEFAULT_FREQ} Hz, vol {DEFAULT_VOL}%");

    // ── GPIO init ────────────────────────────────────────────────────────────
    let gpio = Gpio::new().expect("GPIO init failed – are you on a Pi?");

    let init_cfg = Config::default();
    let init_cfg = { let mut c = init_cfg; c.wpm = wpm; c };

    let dit_pin: InputPin = gpio.get(init_cfg.pin_dit)
        .expect("DIT pin unavailable")
        .into_input_pulldown();

    let dah_pin: InputPin = gpio.get(init_cfg.pin_dah)
        .expect("DAH pin unavailable")
        .into_input_pulldown();

    let tx_sw: InputPin = gpio.get(init_cfg.pin_tx)
        .expect("TX switch pin unavailable")
        .into_input_pulldown();

    let _spk_sw: InputPin = gpio.get(init_cfg.pin_spk)
        .expect("SPK switch pin unavailable")
        .into_input_pulldown();

    let mut ptt: OutputPin = gpio.get(init_cfg.pin_ptt)
        .expect("PTT pin unavailable")
        .into_output_low();

    // ── Sidetone thread ──────────────────────────────────────────────────────
    let key_flag = Arc::new(AtomicBool::new(false));

    // ── Shared runtime config ────────────────────────────────────────────────
    let cfg_mtx: Arc<Mutex<Config>> = Arc::new(Mutex::new({
        let mut c = init_cfg;
        set_system_volume(c.volume);
        c
    }));

    #[cfg(feature = "sidetone")]
    {
        let kf   = key_flag.clone();
        let cfg2 = cfg_mtx.clone();
        thread::Builder::new()
            .name("sidetone".into())
            .spawn(move || run_sidetone(kf, cfg2))
            .expect("sidetone thread spawn failed");
    }

    // ── HTTP server thread ───────────────────────────────────────────────────
    let (http_tx, http_rx): (SyncSender<String>, Receiver<String>) = mpsc::sync_channel(1);

    {
        let cfg2 = cfg_mtx.clone();
        thread::Builder::new()
            .name("http".into())
            .spawn(move || run_http_server(http_tx, cfg2))
            .expect("http thread spawn failed");
    }

    // ── Shutdown signals ─────────────────────────────────────────────────────
    unsafe {
        libc::signal(libc::SIGINT,  on_signal as libc::sighandler_t);
        libc::signal(libc::SIGTERM, on_signal as libc::sighandler_t);
    }

    // ── Keyer loop ────────────────────────────────────────────────────────────
    let mut keyer    = Keyer::new(wpm);
    let mut last_wpm = wpm;
    let poll_period  = Duration::from_millis(1);

    while !SHUTDOWN.load(Ordering::SeqCst) {
        // ── Snapshot config (cheap Mutex lock) ───────────────────────────────
        let cfg = cfg_mtx.lock().unwrap().clone();
        if cfg.wpm != last_wpm {
            keyer.unit = cfg.dit_dur();
            last_wpm   = cfg.wpm;
        }

        // ── Check for web-queued text ────────────────────────────────────────
        if let Ok(text) = http_rx.try_recv() {
            let snap = cfg_mtx.lock().unwrap().clone();
            send_text(&text, &mut ptt, &snap, &key_flag);
            continue;
        }

        // ── Iambic paddle ────────────────────────────────────────────────────
        let dit_dn = dit_pin.is_high();
        let dah_dn = dah_pin.is_high();
        let tx_on  = tx_sw.is_high();
        let rf_key = keyer.tick(dit_dn, dah_dn);

        if tx_on && rf_key {
            ptt.set_high();
            key_flag.store(true, Ordering::Relaxed);
        } else {
            ptt.set_low();
            key_flag.store(false, Ordering::Relaxed);
        }

        thread::sleep(poll_period);
    }

    // ── Clean shutdown ────────────────────────────────────────────────────────
    println!("\nham-cw shutting down — PTT released");
    ptt.set_low();
    key_flag.store(false, Ordering::Relaxed);
}