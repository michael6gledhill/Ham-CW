//! ham-cw — Minimal CW iambic keyer for Raspberry Pi Zero
//!
//! Wiring (BCM numbers, all configurable via CLI flags):
//!   GPIO 12  ← DIT paddle (active-high, internal pull-down)
//!   GPIO 13  ← DAH paddle (active-high, internal pull-down)
//!   GPIO 16  ← TX switch  (active-high ⇒ transmit enabled)
//!   GPIO 20  ← SPK switch (active-high ⇒ speaker-monitor mode)
//!   GPIO 18  → PTT output (high = transmit)
//!
//! Usage:
//!   ham-cw [WPM]          e.g.  ham-cw 20
//!   ham-cw --help

use rppal::gpio::{Gpio, InputPin, OutputPin};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use std::{env, thread};

// Global shutdown flag written only by signal handlers
static SHUTDOWN: AtomicBool = AtomicBool::new(false);

extern "C" fn on_signal(_: libc::c_int) {
    SHUTDOWN.store(true, Ordering::SeqCst);
}

// ─── Default configuration ────────────────────────────────────────────────────

const DEFAULT_WPM:   u32 = 20;    // words per minute
const SIDETONE_HZ:   f32 = 700.0; // sidetone pitch (used in startup message)

#[cfg(feature = "sidetone")]
const SIDETONE_VOL:  f32 = 0.6;   // 0.0 – 1.0
#[cfg(feature = "sidetone")]
const SAMPLE_RATE:   u32 = 44_100;
#[cfg(feature = "sidetone")]
const PERIOD_FRAMES: u32 = 256;   // ~5.8 ms latency at 44100 Hz

const PIN_DIT: u8 = 12;
const PIN_DAH: u8 = 13;
const PIN_TX_SW: u8 = 16;
const PIN_SPK_SW: u8 = 20;
const PIN_PTT: u8 = 18;

// ─── Timing helpers ───────────────────────────────────────────────────────────

fn dit_dur(wpm: u32) -> Duration {
    // Standard PARIS timing: 1 dit = 1200 ms / WPM
    Duration::from_millis(1200 / wpm as u64)
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
    phase:        Phase,
    last:         Option<Element>,
    dit_mem:      bool,
    dah_mem:      bool,
    timer:        Instant,
    unit:         Duration,
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
fn run_sidetone(keyed: Arc<AtomicBool>) {
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
    let phase_step = 2.0 * std::f32::consts::PI * SIDETONE_HZ / SAMPLE_RATE as f32;
    let mut phase: f32 = 0.0;

    loop {
        let on = keyed.load(Ordering::Relaxed);
        for s in &mut buf {
            *s = if on {
                let v = (phase.sin() * 32_767.0 * SIDETONE_VOL) as i16;
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

// ─── Main ─────────────────────────────────────────────────────────────────────

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() > 1 && (args[1] == "--help" || args[1] == "-h") {
        eprintln!(
            "ham-cw — iambic (Mode B) CW keyer\n\
             Usage: ham-cw [WPM]\n\
             Pins (BCM): DIT={}  DAH={}  TX-SW={}  SPK-SW={}  PTT={}\n\
             Default WPM: {}",
            PIN_DIT, PIN_DAH, PIN_TX_SW, PIN_SPK_SW, PIN_PTT, DEFAULT_WPM
        );
        return;
    }

    let wpm: u32 = args.get(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_WPM)
        .max(5)
        .min(60);

    println!("ham-cw starting — {wpm} WPM, sidetone {SIDETONE_HZ:.0} Hz");

    // ── GPIO init ────────────────────────────────────────────────────────────
    let gpio = Gpio::new().expect("GPIO init failed – are you on a Pi?");

    let dit_pin: InputPin = gpio.get(PIN_DIT)
        .expect("DIT pin unavailable")
        .into_input_pulldown();

    let dah_pin: InputPin = gpio.get(PIN_DAH)
        .expect("DAH pin unavailable")
        .into_input_pulldown();

    let tx_sw: InputPin = gpio.get(PIN_TX_SW)
        .expect("TX switch pin unavailable")
        .into_input_pulldown();

    let _spk_sw: InputPin = gpio.get(PIN_SPK_SW)
        .expect("SPK switch pin unavailable")
        .into_input_pulldown();

    let mut ptt: OutputPin = gpio.get(PIN_PTT)
        .expect("PTT pin unavailable")
        .into_output_low();

    // ── Sidetone thread ──────────────────────────────────────────────────────
    let key_flag = Arc::new(AtomicBool::new(false));

    #[cfg(feature = "sidetone")]
    {
        let kf = key_flag.clone();
        thread::Builder::new()
            .name("sidetone".into())
            .spawn(move || run_sidetone(kf))
            .expect("sidetone thread spawn failed");
    }

    // ── Shutdown flag (SIGINT / Ctrl-C) ─────────────────────────────────────
    unsafe {
        libc::signal(libc::SIGINT,  on_signal as libc::sighandler_t);
        libc::signal(libc::SIGTERM, on_signal as libc::sighandler_t);
    }

    // ── Keyer loop ────────────────────────────────────────────────────────────
    let mut keyer   = Keyer::new(wpm);
    let poll_period = Duration::from_millis(1);

    while !SHUTDOWN.load(Ordering::SeqCst) {
        let dit_dn   = dit_pin.is_high();
        let dah_dn   = dah_pin.is_high();
        let tx_on    = tx_sw.is_high();

        let rf_key = keyer.tick(dit_dn, dah_dn);

        // PTT follows the keyed state, but only when the TX switch is in TX position
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


