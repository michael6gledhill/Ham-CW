// Morse code tables, timing logic, and iambic Mode-B keyer.
// Deadline-based timing: every dit and dah is exactly the right length.

use std::collections::HashMap;
use std::sync::LazyLock;

/// Morse code lookup table.
static MORSE: LazyLock<HashMap<char, &'static str>> = LazyLock::new(|| {
    let mut m = HashMap::new();
    m.insert('A', ".-");     m.insert('B', "-...");  m.insert('C', "-.-.");
    m.insert('D', "-..");    m.insert('E', ".");      m.insert('F', "..-.");
    m.insert('G', "--.");    m.insert('H', "....");   m.insert('I', "..");
    m.insert('J', ".---");   m.insert('K', "-.-");    m.insert('L', ".-..");
    m.insert('M', "--");     m.insert('N', "-.");     m.insert('O', "---");
    m.insert('P', ".--.");   m.insert('Q', "--.-");   m.insert('R', ".-.");
    m.insert('S', "...");    m.insert('T', "-");      m.insert('U', "..-");
    m.insert('V', "...-");   m.insert('W', ".--");    m.insert('X', "-..-");
    m.insert('Y', "-.--");   m.insert('Z', "--..");
    m.insert('0', "-----");  m.insert('1', ".----");  m.insert('2', "..---");
    m.insert('3', "...--");  m.insert('4', "....-");  m.insert('5', ".....");
    m.insert('6', "-....");  m.insert('7', "--...");   m.insert('8', "---..");
    m.insert('9', "----.");
    m.insert('.', ".-.-.-"); m.insert(',', "--..--");  m.insert('?', "..--..");
    m.insert('/', "-..-.");  m.insert('=', "-...-");   m.insert(':', "---...");
    m.insert(';', "-.-.-."); m.insert('+', ".-.-.");   m.insert('-', "-....-");
    m.insert('_', "..--.-"); m.insert('"', ".-..-."); m.insert('\'', ".----.");
    m.insert('(', "-.--.");  m.insert(')', "-.--.-");  m.insert('!', "-.-.--");
    m.insert('@', ".--.-.");
    m
});

/// Standard dit duration in seconds: 1200ms / WPM.
pub fn dit_duration(wpm: i32) -> f64 {
    1.2 / wpm.max(1) as f64
}

/// Return (dit_s, dah_s, gap_s) for a given WPM.
pub fn get_timing(wpm: i32) -> (f64, f64, f64) {
    let d = dit_duration(wpm);
    (d, d * 3.0, d)
}

/// Which element the keyer is producing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Element {
    Dit,
    Dah,
}

/// Keyer state machine states.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyerState {
    Idle,
    Sending,
    Spacing,
}

/// Iambic Mode-B keyer with deadline-based timing.
///
/// Pure logic — no I/O.  Call `tick(now, dit, dah)` where `now` is
/// `Instant::now()` converted to seconds (or any monotonic f64).
/// Returns `true` when the tone should be ON.
///
/// Uses absolute deadlines instead of elapsed-time accumulation so
/// that polling jitter never makes elements longer or shorter than
/// they should be.
pub struct Keyer {
    pub state: KeyerState,
    pub element: Option<Element>,
    pub mem: Option<Element>,
    pub deadline: f64,
    pub dit_len: f64,
    pub dah_len: f64,
    pub gap_len: f64,
}

impl Keyer {
    pub fn new(wpm: i32) -> Self {
        let (dit_len, dah_len, gap_len) = get_timing(wpm);
        Self {
            state: KeyerState::Idle,
            element: None,
            mem: None,
            deadline: 0.0,
            dit_len,
            dah_len,
            gap_len,
        }
    }

    pub fn update(&mut self, wpm: i32) {
        let (d, dah, g) = get_timing(wpm);
        self.dit_len = d;
        self.dah_len = dah;
        self.gap_len = g;
    }

    #[allow(dead_code)]
    pub fn reset(&mut self) {
        self.state = KeyerState::Idle;
        self.element = None;
        self.mem = None;
    }

    fn pick_live(&self, dit: bool, dah: bool) -> Option<Element> {
        if dit && dah {
            return Some(if self.element == Some(Element::Dit) {
                Element::Dah
            } else {
                Element::Dit
            });
        }
        if dit {
            return Some(Element::Dit);
        }
        if dah {
            return Some(Element::Dah);
        }
        None
    }

    fn pick_mem(&mut self, dit: bool, dah: bool) -> Option<Element> {
        if let Some(m) = self.mem.take() {
            Some(m)
        } else {
            self.pick_live(dit, dah)
        }
    }

    fn element_dur(&self, el: Element) -> f64 {
        match el {
            Element::Dit => self.dit_len,
            Element::Dah => self.dah_len,
        }
    }

    /// Advance keyer at monotonic time `now`. Returns `true` = tone ON.
    pub fn tick(&mut self, now: f64, dit: bool, dah: bool) -> bool {
        match self.state {
            KeyerState::Idle => {
                let nxt = match self.pick_live(dit, dah) {
                    Some(e) => e,
                    None => return false,
                };
                self.element = Some(nxt);
                self.deadline = now + self.element_dur(nxt);
                self.state = KeyerState::Sending;
                true
            }
            KeyerState::Sending => {
                // Latch opposite paddle into memory (Mode-B)
                if self.element == Some(Element::Dit) && dah {
                    self.mem = Some(Element::Dah);
                } else if self.element == Some(Element::Dah) && dit {
                    self.mem = Some(Element::Dit);
                }
                if now < self.deadline {
                    return true;
                }
                // Element finished → inter-element gap
                self.deadline += self.gap_len;
                self.state = KeyerState::Spacing;
                false
            }
            KeyerState::Spacing => {
                if now < self.deadline {
                    return false;
                }
                let nxt = match self.pick_mem(dit, dah) {
                    Some(e) => e,
                    None => {
                        self.state = KeyerState::Idle;
                        return false;
                    }
                };
                self.element = Some(nxt);
                self.deadline += self.element_dur(nxt);
                self.state = KeyerState::Sending;
                true
            }
        }
    }
}

/// A tone element for text-to-morse conversion.
#[derive(Debug, Clone, Copy)]
pub struct ToneElement {
    pub on: bool,
    pub duration: f64,
}

/// Convert text to a list of (on/off, seconds) elements.
pub fn text_to_elements(text: &str, wpm: i32) -> Vec<ToneElement> {
    let (dit_s, dah_s, gap_s) = get_timing(wpm);
    let mut elements = Vec::new();
    let mut prev_char = false;

    for ch in text.to_uppercase().chars() {
        if ch == ' ' {
            if prev_char {
                elements.push(ToneElement {
                    on: false,
                    duration: gap_s * 7.0,
                });
            }
            prev_char = false;
            continue;
        }

        let code = match MORSE.get(&ch) {
            Some(c) => *c,
            None => continue,
        };

        if prev_char {
            elements.push(ToneElement {
                on: false,
                duration: gap_s * 3.0,
            });
        }

        for (j, sym) in code.chars().enumerate() {
            if j > 0 {
                elements.push(ToneElement {
                    on: false,
                    duration: gap_s,
                });
            }
            elements.push(ToneElement {
                on: true,
                duration: if sym == '.' { dit_s } else { dah_s },
            });
        }

        prev_char = true;
    }

    elements
}
