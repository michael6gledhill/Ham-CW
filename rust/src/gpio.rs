// GPIO management for Raspberry Pi via rppal.
//
// Provides:
//   - Input pin reading (paddles, switches) with internal pull-ups
//   - Speaker PWM output
//   - GPIO auto-detection via raw polling at 200 Hz

#[cfg(target_os = "linux")]
use rppal::gpio::{Gpio, InputPin, Level, OutputPin};

#[cfg(target_os = "linux")]
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Instant;

// --------------------------------------------------------------------------
//  GPIO device manager
// --------------------------------------------------------------------------

pub struct GpioManager {
    #[cfg(target_os = "linux")]
    gpio: Option<Gpio>,
    #[cfg(target_os = "linux")]
    inputs: HashMap<String, InputPin>,
    #[cfg(target_os = "linux")]
    speaker_pwm: Option<rppal::gpio::IoPin>,
    #[cfg(target_os = "linux")]
    speaker_gnd: Option<OutputPin>,

    #[cfg(not(target_os = "linux"))]
    _phantom: (),
}

impl GpioManager {
    pub fn new() -> Self {
        #[cfg(target_os = "linux")]
        {
            let gpio = Gpio::new().ok();
            if gpio.is_some() {
                println!("morse-keyer: rppal GPIO initialized");
            } else {
                println!("morse-keyer: rppal GPIO unavailable");
            }
            Self {
                gpio,
                inputs: HashMap::new(),
                speaker_pwm: None,
                speaker_gnd: None,
            }
        }
        #[cfg(not(target_os = "linux"))]
        {
            println!("morse-keyer: GPIO not available on this platform");
            Self { _phantom: () }
        }
    }

    /// Close all pins.
    pub fn close(&mut self) {
        #[cfg(target_os = "linux")]
        {
            self.inputs.clear();
            self.speaker_pwm = None;
            self.speaker_gnd = None;
        }
    }

    /// Set up GPIO pins from config. Closes existing pins first.
    pub fn setup(&mut self, _cfg: &crate::settings::Config) {
        self.close();

        #[cfg(target_os = "linux")]
        {
            let gpio = match &self.gpio {
                Some(g) => g,
                None => return,
            };
            let cfg = _cfg;

            // Input pins (pull-up, active when grounded)
            for role in &[
                "pin_freq_up",
                "pin_freq_down",
                "pin_speed_up",
                "pin_speed_down",
                "pin_settings",
                "pin_dot",
                "pin_dash",
            ] {
                let pin_num = cfg.get_pin(role);
                if (0..=27).contains(&pin_num) {
                    match gpio.get(pin_num as u8) {
                        Ok(pin) => {
                            self.inputs
                                .insert(role.to_string(), pin.into_input_pullup());
                        }
                        Err(e) => {
                            eprintln!("morse-keyer: GPIO setup {role} pin {pin_num}: {e}");
                        }
                    }
                }
            }

            // Speaker PWM output
            let spk = cfg.pin_speaker_1;
            if (0..=27).contains(&spk) {
                match gpio.get(spk as u8) {
                    Ok(pin) => {
                        self.speaker_pwm = Some(pin.into_io(rppal::gpio::Mode::Output));
                    }
                    Err(e) => eprintln!("morse-keyer: speaker PWM pin {spk}: {e}"),
                }
            }

            // Speaker ground (tied LOW)
            let gnd = cfg.pin_speaker_2;
            if (0..=27).contains(&gnd) {
                match gpio.get(gnd as u8) {
                    Ok(pin) => {
                        let mut out = pin.into_output();
                        out.set_low();
                        self.speaker_gnd = Some(out);
                    }
                    Err(e) => eprintln!("morse-keyer: speaker GND pin {gnd}: {e}"),
                }
            }
        }
    }

    /// Read a button-type GPIO. Returns true when grounded (pressed).
    pub fn read_pin(&self, _role: &str) -> bool {
        #[cfg(target_os = "linux")]
        {
            if let Some(pin) = self.inputs.get(_role) {
                return pin.read() == Level::Low;
            }
        }
        false
    }

    /// Read both paddles at once.
    pub fn read_paddles(&self) -> (bool, bool) {
        (self.read_pin("pin_dot"), self.read_pin("pin_dash"))
    }

    /// Turn speaker on with software square wave approximation.
    pub fn speaker_on(&mut self) {
        #[cfg(target_os = "linux")]
        {
            if let Some(ref mut pin) = self.speaker_pwm {
                pin.set_high();
            }
        }
    }

    /// Turn speaker off.
    pub fn speaker_off(&mut self) {
        #[cfg(target_os = "linux")]
        {
            if let Some(ref mut pin) = self.speaker_pwm {
                pin.set_low();
            }
        }
    }
}

// --------------------------------------------------------------------------
//  GPIO auto-detector (raw polling at 200Hz)
// --------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct DetectionStatus {
    pub detecting: bool,
    pub detected_pins: Vec<u8>,
    pub timed_out: bool,
    pub error: Option<String>,
    pub role: Option<String>,
    pub elapsed: f64,
}

pub struct GpioDetector {
    inner: Arc<Mutex<DetectorInner>>,
}

struct DetectorInner {
    detecting: bool,
    detected_pins: Vec<u8>,
    timed_out: bool,
    error: Option<String>,
    role: Option<String>,
    start_time: Instant,
    stop_flag: bool,
}

impl GpioDetector {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(DetectorInner {
                detecting: false,
                detected_pins: Vec::new(),
                timed_out: false,
                error: None,
                role: None,
                start_time: Instant::now(),
                stop_flag: false,
            })),
        }
    }

    pub fn start(&self, role: &str, exclude_pins: &[u8]) {
        self.stop();

        {
            let mut inner = self.inner.lock().unwrap();
            inner.detecting = true;
            inner.detected_pins.clear();
            inner.timed_out = false;
            inner.error = None;
            inner.role = Some(role.to_string());
            inner.start_time = Instant::now();
            inner.stop_flag = false;
        }

        let inner = Arc::clone(&self.inner);
        let exclude: Vec<u8> = exclude_pins.to_vec();

        std::thread::spawn(move || {
            Self::poll_loop(inner, &exclude);
        });
    }

    pub fn stop(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.stop_flag = true;
        inner.detecting = false;
    }

    pub fn get_status(&self) -> DetectionStatus {
        let inner = self.inner.lock().unwrap();
        DetectionStatus {
            detecting: inner.detecting,
            detected_pins: inner.detected_pins.clone(),
            timed_out: inner.timed_out,
            error: inner.error.clone(),
            role: inner.role.clone(),
            elapsed: if inner.detecting {
                inner.start_time.elapsed().as_secs_f64()
            } else {
                0.0
            },
        }
    }

    #[cfg(target_os = "linux")]
    fn poll_loop(inner: Arc<Mutex<DetectorInner>>, exclude: &[u8]) {
        use rppal::gpio::Gpio;

        let gpio = match Gpio::new() {
            Ok(g) => g,
            Err(e) => {
                let mut lock = inner.lock().unwrap();
                lock.error = Some(format!("GPIO init failed: {e}"));
                lock.detecting = false;
                return;
            }
        };

        // Set up all pins 0-27 as inputs with pull-up
        let mut pins: Vec<(u8, InputPin)> = Vec::new();
        for pin_num in 0..=27u8 {
            if exclude.contains(&pin_num) {
                continue;
            }
            match gpio.get(pin_num) {
                Ok(pin) => pins.push((pin_num, pin.into_input_pullup())),
                Err(_) => continue,
            }
        }

        // Let pull-ups settle
        std::thread::sleep(std::time::Duration::from_millis(50));

        // Record initial state
        let mut initial: HashMap<u8, Level> = HashMap::new();
        let mut confirmed: std::collections::HashSet<u8> = std::collections::HashSet::new();
        let mut prev_read: HashMap<u8, Level> = HashMap::new();

        for (num, pin) in &pins {
            let val = pin.read();
            initial.insert(*num, val);
            prev_read.insert(*num, val);
        }

        let role = inner.lock().unwrap().role.clone().unwrap_or_default();
        println!("morse-keyer: detector polling {} pins for {role}", pins.len());

        let timeout = std::time::Duration::from_secs(10);

        loop {
            {
                let lock = inner.lock().unwrap();
                if lock.stop_flag || !lock.detecting {
                    break;
                }
                if lock.start_time.elapsed() >= timeout {
                    drop(lock);
                    let mut lock = inner.lock().unwrap();
                    lock.timed_out = true;
                    lock.detecting = false;
                    println!("morse-keyer: detection timed out");
                    break;
                }
            }

            for (num, pin) in &pins {
                if confirmed.contains(num) {
                    continue;
                }
                let val = pin.read();
                let init = initial[num];

                if val != init {
                    // Check stability: same as previous read
                    if prev_read.get(num) == Some(&val) {
                        confirmed.insert(*num);
                        let mut lock = inner.lock().unwrap();
                        lock.detected_pins.insert(0, *num);
                        println!(
                            "morse-keyer: detected GPIO {num} (was {init:?}, now {val:?})"
                        );
                    }
                }
                prev_read.insert(*num, val);
            }

            std::thread::sleep(std::time::Duration::from_millis(5));
        }

        // Pins are dropped automatically (rppal resets them)
    }

    #[cfg(not(target_os = "linux"))]
    fn poll_loop(inner: Arc<Mutex<DetectorInner>>, _exclude: &[u8]) {
        let mut lock = inner.lock().unwrap();
        lock.error = Some("GPIO detection not available on this platform".to_string());
        lock.detecting = false;
    }
}
