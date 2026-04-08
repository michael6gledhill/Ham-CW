"""Configuration for ham-cw keyer.

Stores all settings (WPM, tone frequency, GPIO pin assignments) in a
JSON file next to the application.  Thread-safe reads and writes.
"""

import json
import os
import threading

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'config.json')

DEFAULTS = {
    'wpm': 20,
    'freq': 700,
    'pin_spk': 20,
    'pin_spk_gnd': 21,
    'pin_dit': 27,
    'pin_dah': 22,
    'pin_mode': 26,
    'pin_tx': 16,
    'pin_tone_up': 5,
    'pin_tone_down': 6,
    'pin_wpm_up': 13,
    'pin_wpm_down': 19,
}

LIMITS = {
    'wpm': (5, 50),
    'freq': (200, 2000),
}

STEPS = {
    'wpm': 1,
    'freq': 50,
}

_lock = threading.Lock()
_config = dict(DEFAULTS)


def load_config():
    """Load configuration from disk, merging with defaults."""
    global _config
    with _lock:
        try:
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
            merged = dict(DEFAULTS)
            merged.update(saved)
            _config = merged
        except (FileNotFoundError, json.JSONDecodeError):
            _config = dict(DEFAULTS)


def save_config():
    """Save current configuration to disk."""
    with _lock:
        cfg = dict(_config)
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        print(f"ham-cw: failed to save config: {e}")


def get_config():
    """Return a snapshot of the current configuration."""
    with _lock:
        return dict(_config)


def update_config(updates):
    """Update config with a dict of new values."""
    with _lock:
        for key, val in updates.items():
            if key not in DEFAULTS:
                continue
            if key.startswith('pin_'):
                v = int(val)
                if 0 <= v <= 27:
                    _config[key] = v
            elif key in LIMITS:
                lo, hi = LIMITS[key]
                _config[key] = max(lo, min(hi, int(val)))
    save_config()


def adjust_param(param, direction):
    """Adjust a parameter by one step.  Returns the new value."""
    with _lock:
        if param not in STEPS:
            return _config.get(param)
        step = STEPS[param]
        lo, hi = LIMITS[param]
        _config[param] = max(lo, min(hi, _config[param] + step * direction))
        val = _config[param]
    save_config()
    return val
