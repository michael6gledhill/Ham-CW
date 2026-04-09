// Settings management for ham-cw morse keyer.
// Loads and saves all configuration to settings.json.
// Thread-safe reads and writes via RwLock.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::RwLock;

/// All GPIO role names that support auto-detection.
pub const AUTO_DETECT_PINS: &[&str] = &[
    "pin_freq_up",
    "pin_freq_down",
    "pin_speed_up",
    "pin_speed_down",
    "pin_settings",
    "pin_dot",
    "pin_dash",
];

/// All GPIO role names including speaker pins.
pub const GPIO_PINS: &[&str] = &[
    "pin_freq_up",
    "pin_freq_down",
    "pin_speed_up",
    "pin_speed_down",
    "pin_settings",
    "pin_dot",
    "pin_dash",
    "pin_speaker_1",
    "pin_speaker_2",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub frequency: i32,
    pub wpm: i32,
    pub pin_freq_up: i32,
    pub pin_freq_down: i32,
    pub pin_speed_up: i32,
    pub pin_speed_down: i32,
    pub pin_settings: i32,
    pub pin_dot: i32,
    pub pin_dash: i32,
    pub pin_speaker_1: i32,
    pub pin_speaker_2: i32,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            frequency: 800,
            wpm: 20,
            pin_freq_up: 5,
            pin_freq_down: 6,
            pin_speed_up: 13,
            pin_speed_down: 19,
            pin_settings: 26,
            pin_dot: 27,
            pin_dash: 22,
            pin_speaker_1: 20,
            pin_speaker_2: 21,
        }
    }
}

impl Config {
    /// Get pin value by role name.
    pub fn get_pin(&self, role: &str) -> i32 {
        match role {
            "pin_freq_up" => self.pin_freq_up,
            "pin_freq_down" => self.pin_freq_down,
            "pin_speed_up" => self.pin_speed_up,
            "pin_speed_down" => self.pin_speed_down,
            "pin_settings" => self.pin_settings,
            "pin_dot" => self.pin_dot,
            "pin_dash" => self.pin_dash,
            "pin_speaker_1" => self.pin_speaker_1,
            "pin_speaker_2" => self.pin_speaker_2,
            _ => -1,
        }
    }

    /// Set pin value by role name (validated 0-27).
    pub fn set_pin(&mut self, role: &str, val: i32) {
        if !(0..=27).contains(&val) {
            return;
        }
        match role {
            "pin_freq_up" => self.pin_freq_up = val,
            "pin_freq_down" => self.pin_freq_down = val,
            "pin_speed_up" => self.pin_speed_up = val,
            "pin_speed_down" => self.pin_speed_down = val,
            "pin_settings" => self.pin_settings = val,
            "pin_dot" => self.pin_dot = val,
            "pin_dash" => self.pin_dash = val,
            "pin_speaker_1" => self.pin_speaker_1 = val,
            "pin_speaker_2" => self.pin_speaker_2 = val,
            _ => {}
        }
    }
}

/// Limits for numeric parameters.
pub fn limits(param: &str) -> Option<(i32, i32)> {
    match param {
        "frequency" => Some((400, 1000)),
        "wpm" => Some((5, 50)),
        _ => None,
    }
}

pub struct Settings {
    config: RwLock<Config>,
    path: PathBuf,
}

impl Settings {
    pub fn new(base_dir: &Path) -> Self {
        Self {
            config: RwLock::new(Config::default()),
            path: base_dir.join("settings.json"),
        }
    }

    pub fn load(&self) {
        let mut cfg = Config::default();
        if let Ok(data) = fs::read_to_string(&self.path) {
            if let Ok(saved) = serde_json::from_str::<Config>(&data) {
                cfg = saved;
            }
        } else {
            // No file yet — save defaults
            self.save_inner(&cfg);
        }
        *self.config.write().unwrap() = cfg;
    }

    fn save_inner(&self, cfg: &Config) {
        if let Ok(data) = serde_json::to_string_pretty(cfg) {
            if let Err(e) = fs::write(&self.path, data) {
                eprintln!("morse-keyer: failed to save settings: {e}");
            }
        }
    }

    pub fn save(&self) {
        let cfg = self.config.read().unwrap().clone();
        self.save_inner(&cfg);
    }

    pub fn get(&self) -> Config {
        self.config.read().unwrap().clone()
    }

    /// Update settings from a partial JSON object.
    pub fn update(&self, updates: &serde_json::Value) {
        let mut cfg = self.config.write().unwrap();
        if let Some(obj) = updates.as_object() {
            for (key, val) in obj {
                if key.starts_with("pin_") {
                    if let Some(v) = val.as_i64() {
                        cfg.set_pin(key, v as i32);
                    }
                } else if let Some((lo, hi)) = limits(key) {
                    if let Some(v) = val.as_i64() {
                        let v = (v as i32).clamp(lo, hi);
                        match key.as_str() {
                            "frequency" => cfg.frequency = v,
                            "wpm" => cfg.wpm = v,
                            _ => {}
                        }
                    }
                }
            }
        }
        self.save_inner(&cfg);
    }

    /// Adjust a numeric parameter by step. Returns new value.
    pub fn adjust(&self, param: &str, step: i32) -> Option<i32> {
        let (lo, hi) = limits(param)?;
        let mut cfg = self.config.write().unwrap();
        let val = match param {
            "frequency" => &mut cfg.frequency,
            "wpm" => &mut cfg.wpm,
            _ => return None,
        };
        *val = (*val + step).clamp(lo, hi);
        let result = *val;
        drop(cfg);
        self.save();
        Some(result)
    }

    #[allow(dead_code)]
    pub fn reset(&self) {
        *self.config.write().unwrap() = Config::default();
        self.save();
    }
}
