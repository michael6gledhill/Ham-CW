"""Configuration management for ham-cw keyer.

Stores all settings and GPIO pin assignments.  Thread-safe access via
get_config() / apply_config().  Persists to ~/.ham-cw.conf as JSON.
"""

import json
import pathlib
import threading

CONFIG_PATH = pathlib.Path.home() / ".ham-cw.conf"

# ---------------------------------------------------------------------------
#  Defaults & limits
# ---------------------------------------------------------------------------
DEFAULTS = {
    # Keyer settings
    "wpm": 20,              # Words per minute
    "freq": 700,            # Sidetone frequency (Hz)
    "volume": 70,           # Output volume 0-100
    "weight": 300,          # Dash weight (300 = standard 3:1 ratio)

    # GPIO pins (BCM numbering)
    "pin_dit": 27,          # DIT paddle input  (active-low, pull-up)
    "pin_dah": 22,          # DAH paddle input  (active-low, pull-up)
    "pin_sw_up": 5,         # Switch A: increment position
    "pin_sw_down": 6,       # Switch A: decrement position
    "pin_sw_sel": 13,       # Switch B: parameter select (cycle on flip)
    "pin_spk": 20,          # Speaker + (PWM output)
    "pin_spk_gnd": 21,      # Speaker - (held LOW as ground ref)
    "pin_ptt": 16,          # PTT output (HIGH when keying)
}

LIMITS = {
    "wpm":    (5, 40),
    "freq":   (300, 1000),
    "volume": (0, 100),
    "weight": (200, 500),
}

# Step sizes used by the physical adjustment switch
STEPS = {
    "wpm": 1,
    "freq": 50,
    "volume": 5,
}

# Parameters that Switch B cycles through
PARAMS = ["wpm", "freq", "volume"]

# ---------------------------------------------------------------------------
#  Thread-safe config store
# ---------------------------------------------------------------------------
_config = dict(DEFAULTS)
_lock = threading.Lock()


def _clamp(val, lo, hi):
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return lo


def load_config():
    """Load configuration from disk, merging into defaults."""
    global _config
    try:
        data = json.loads(CONFIG_PATH.read_text())
        with _lock:
            for k in DEFAULTS:
                if k in data:
                    _config[k] = data[k]
        print(f"ham-cw: loaded config from {CONFIG_PATH}")
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        print(f"ham-cw: using defaults ({e})")


def save_config():
    """Persist current config to disk."""
    with _lock:
        data = dict(_config)
    try:
        CONFIG_PATH.write_text(json.dumps(data, indent=2))
    except OSError as e:
        print(f"ham-cw: save error: {e}")


def get_config():
    """Return a snapshot of the current config dict."""
    with _lock:
        return dict(_config)


def apply_config(vals):
    """Merge *vals* into config with clamping.  Saves and returns result."""
    with _lock:
        for key, (lo, hi) in LIMITS.items():
            if key in vals:
                _config[key] = _clamp(vals[key], lo, hi)
        for key in DEFAULTS:
            if key.startswith("pin_") and key in vals:
                _config[key] = _clamp(vals[key], 0, 27)
        result = dict(_config)
    save_config()
    return result


def adjust_param(param, direction):
    """Adjust *param* by one step.  *direction* is +1 or -1.
    Returns the new value."""
    step = STEPS.get(param, 1)
    lo, hi = LIMITS.get(param, (0, 100))
    with _lock:
        _config[param] = _clamp(_config[param] + step * direction, lo, hi)
        val = _config[param]
    save_config()
    return val
