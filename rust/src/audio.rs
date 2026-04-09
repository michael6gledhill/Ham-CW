// Audio generation and playback for CW tones.
//
// Uses cpal for cross-platform audio output, or raw ALSA as fallback.
// Runs in a background thread with ~12ms latency.
// 5ms raised-cosine envelope ramp eliminates key-click artefacts.

#[cfg(target_os = "linux")]
use std::f64::consts::PI;
use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};
use std::sync::Arc;

#[cfg(target_os = "linux")]
const SAMPLE_RATE: u32 = 44100;
#[cfg(target_os = "linux")]
const BUFFER_SIZE: usize = 512;
#[cfg(target_os = "linux")]
const RAMP_MS: f64 = 5.0;
#[cfg(target_os = "linux")]
const RAMP_SAMPLES: usize = (SAMPLE_RATE as f64 * RAMP_MS / 1000.0) as usize;
#[cfg(target_os = "linux")]
const TWO_PI: f64 = 2.0 * PI;

/// Shared audio state — can be accessed from the keyer thread.
pub struct AudioState {
    pub key_on: AtomicBool,
    pub frequency: AtomicI32,
}

impl AudioState {
    pub fn new(freq: i32) -> Self {
        Self {
            key_on: AtomicBool::new(false),
            frequency: AtomicI32::new(freq),
        }
    }
}

pub struct AudioEngine {
    state: Arc<AudioState>,
    running: Arc<AtomicBool>,
    thread: Option<std::thread::JoinHandle<()>>,
}

impl AudioEngine {
    pub fn new() -> Self {
        Self {
            state: Arc::new(AudioState::new(800)),
            running: Arc::new(AtomicBool::new(false)),
            thread: None,
        }
    }

    #[allow(dead_code)]
    pub fn state(&self) -> Arc<AudioState> {
        Arc::clone(&self.state)
    }

    pub fn set_frequency(&self, freq: i32) {
        self.state
            .frequency
            .store(freq.clamp(400, 1000), Ordering::Relaxed);
    }

    pub fn key_on(&self) {
        self.state.key_on.store(true, Ordering::Relaxed);
    }

    pub fn key_off(&self) {
        self.state.key_on.store(false, Ordering::Relaxed);
    }

    /// Start the audio playback thread.
    pub fn start(&mut self) {
        if self.running.load(Ordering::Relaxed) {
            return;
        }
        self.running.store(true, Ordering::Relaxed);

        let running = Arc::clone(&self.running);
        let audio_state = Arc::clone(&self.state);

        self.thread = Some(std::thread::spawn(move || {
            if let Err(e) = audio_loop(running, audio_state) {
                eprintln!("morse-keyer: audio error: {e}");
            }
        }));
    }

    pub fn stop(&mut self) {
        self.running.store(false, Ordering::Relaxed);
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
    }
}

impl Drop for AudioEngine {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Try cpal first, then raw ALSA write, then silent.
fn audio_loop(running: Arc<AtomicBool>, state: Arc<AudioState>) -> Result<(), String> {
    // Try cpal
    #[cfg(target_os = "linux")]
    {
        if let Ok(()) = audio_loop_cpal(Arc::clone(&running), Arc::clone(&state)) {
            return Ok(());
        }
        eprintln!("morse-keyer: cpal failed, trying raw ALSA...");
        if let Ok(()) = audio_loop_alsa(&running, &state) {
            return Ok(());
        }
        eprintln!("morse-keyer: ALSA failed too — speaker GPIO only");
    }

    #[cfg(not(target_os = "linux"))]
    {
        let _ = &state;
        eprintln!("morse-keyer: no audio backend on this platform — speaker GPIO only");
    }

    // Fallback: just spin doing nothing (GPIO speaker still works)
    while running.load(Ordering::Relaxed) {
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn audio_loop_cpal(running: Arc<AtomicBool>, state: Arc<AudioState>) -> Result<(), String> {
    use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};

    let host = cpal::default_host();
    let device = host
        .default_output_device()
        .ok_or("no output device")?;

    let config = cpal::StreamConfig {
        channels: 1,
        sample_rate: cpal::SampleRate(SAMPLE_RATE),
        buffer_size: cpal::BufferSize::Fixed(BUFFER_SIZE as u32),
    };

    let mut phase = 0.0f64;
    let mut envelope = 0.0f64;
    let ramp_inc = 1.0 / RAMP_SAMPLES.max(1) as f64;

    let cb_running = Arc::clone(&running);
    let cb_state = Arc::clone(&state);

    let stream = device
        .build_output_stream(
            &config,
            move |data: &mut [i16], _: &cpal::OutputCallbackInfo| {
                if !cb_running.load(Ordering::Relaxed) {
                    for s in data.iter_mut() {
                        *s = 0;
                    }
                    return;
                }

                let key_on = cb_state.key_on.load(Ordering::Relaxed);
                let freq = cb_state.frequency.load(Ordering::Relaxed) as f64;
                let phase_inc = TWO_PI * freq / SAMPLE_RATE as f64;

                for s in data.iter_mut() {
                    if key_on {
                        envelope = (envelope + ramp_inc).min(1.0);
                    } else {
                        envelope = (envelope - ramp_inc).max(0.0);
                    }

                    if envelope > 0.0 {
                        let shaped = 0.5 - 0.5 * (PI * envelope).cos();
                        *s = (32767.0 * shaped * phase.sin()) as i16;
                        phase += phase_inc;
                        if phase >= TWO_PI {
                            phase -= TWO_PI;
                        }
                    } else {
                        *s = 0;
                        phase = 0.0;
                    }
                }
            },
            |err| eprintln!("morse-keyer: audio stream error: {err}"),
            None,
        )
        .map_err(|e| e.to_string())?;

    stream.play().map_err(|e| e.to_string())?;
    println!("morse-keyer: audio via cpal");

    while running.load(Ordering::Relaxed) {
        std::thread::sleep(std::time::Duration::from_millis(50));
    }

    drop(stream);
    Ok(())
}

#[cfg(target_os = "linux")]
fn audio_loop_alsa(running: &AtomicBool, state: &AudioState) -> Result<(), String> {
    use alsa::pcm::{Access, Format, HwParams, PCM};
    use alsa::{Direction, ValueOr};

    let devices = ["plughw:Headphones", "plughw:2,0", "plughw:1,0", "plughw:0,0", "default"];
    let mut pcm_opt = None;

    for dev in &devices {
        match PCM::new(dev, Direction::Playback, false) {
            Ok(pcm) => {
                {
                    let hwp = HwParams::any(&pcm).map_err(|e| e.to_string())?;
                    hwp.set_channels(1).map_err(|e| e.to_string())?;
                    hwp.set_rate(SAMPLE_RATE, ValueOr::Nearest).map_err(|e| e.to_string())?;
                    hwp.set_format(Format::s16()).map_err(|e| e.to_string())?;
                    hwp.set_access(Access::RWInterleaved).map_err(|e| e.to_string())?;
                    hwp.set_period_size(BUFFER_SIZE as i32, ValueOr::Nearest).map_err(|e| e.to_string())?;
                    pcm.hw_params(&hwp).map_err(|e| e.to_string())?;
                } // hwp dropped here, releasing borrow on pcm
                println!("morse-keyer: audio via ALSA ({dev})");
                pcm_opt = Some(pcm);
                break;
            }
            Err(_) => continue,
        }
    }

    let pcm = pcm_opt.ok_or("no ALSA device")?;
    let io = pcm.io_i16().map_err(|e| e.to_string())?;

    let mut phase = 0.0f64;
    let mut envelope = 0.0f64;
    let ramp_inc = 1.0 / RAMP_SAMPLES.max(1) as f64;
    let mut buf = vec![0i16; BUFFER_SIZE];

    while running.load(Ordering::Relaxed) {
        let key_on = state.key_on.load(Ordering::Relaxed);
        let freq = state.frequency.load(Ordering::Relaxed) as f64;
        let phase_inc = TWO_PI * freq / SAMPLE_RATE as f64;

        // Fast path: total silence
        if !key_on && envelope <= 0.0 {
            for s in buf.iter_mut() {
                *s = 0;
            }
        } else {
            for s in buf.iter_mut() {
                if key_on {
                    envelope = (envelope + ramp_inc).min(1.0);
                } else {
                    envelope = (envelope - ramp_inc).max(0.0);
                }
                if envelope > 0.0 {
                    let shaped = 0.5 - 0.5 * (PI * envelope).cos();
                    *s = (32767.0 * shaped * phase.sin()) as i16;
                    phase += phase_inc;
                    if phase >= TWO_PI {
                        phase -= TWO_PI;
                    }
                } else {
                    *s = 0;
                    phase = 0.0;
                }
            }
        }

        let _ = io.writei(&buf);
    }

    Ok(())
}
