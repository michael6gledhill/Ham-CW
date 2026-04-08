"""Settings management for ham-cw morse keyer.

Loads and saves all configuration to settings.json.
Thread-safe reads and writes.
"""

import json
import os
import threading

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'settings.json')

DEFAULTS = {
    'frequency':       800,
    'wpm':             20,
    'pin_freq_up':     5,
    'pin_freq_down':   6,
    'pin_speed_up':    13,
    'pin_speed_down':  19,
    'pin_settings':    26,
    'pin_dot':         27,
    'pin_dash':        22,
    'pin_speaker_1':   20,
    'pin_speaker_2':   21,
}

# GPIO roles that can be auto-detected (all except speaker pins)
AUTO_DETECT_PINS = [
    'pin_freq_up', 'pin_freq_down',
    'pin_speed_up', 'pin_speed_down',
    'pin_settings',
    'pin_dot', 'pin_dash',
]

# All GPIO roles
GPIO_PINS = AUTO_DETECT_PINS + ['pin_speaker_1', 'pin_speaker_2']

LIMITS = {
    'frequency': (400, 1000),
    'wpm':       (5, 50),
}

_lock = threading.Lock()
_settings = dict(DEFAULTS)


def load():
    """Load settings from JSON file, merging with defaults."""
    global _settings
    with _lock:
        try:
            with open(SETTINGS_PATH) as f:
                saved = json.load(f)
            merged = dict(DEFAULTS)
            merged.update(saved)
            _settings = merged
        except (FileNotFoundError, json.JSONDecodeError):
            _settings = dict(DEFAULTS)
            _save_locked()


def _save_locked():
    """Save current settings (caller must hold _lock)."""
    data = dict(_settings)
    try:
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"morse-keyer: failed to save settings: {e}")


def save():
    """Force save current settings to disk."""
    with _lock:
        _save_locked()


def get():
    """Return a snapshot of current settings (thread-safe)."""
    with _lock:
        return dict(_settings)


def update(updates):
    """Update settings with validated values and save."""
    with _lock:
        for key, val in updates.items():
            if key not in DEFAULTS:
                continue
            if key.startswith('pin_'):
                v = int(val)
                if 0 <= v <= 27:
                    _settings[key] = v
            elif key in LIMITS:
                lo, hi = LIMITS[key]
                _settings[key] = max(lo, min(hi, int(val)))
        _save_locked()


def reset():
    """Reset all settings to defaults and save."""
    global _settings
    with _lock:
        _settings = dict(DEFAULTS)
        _save_locked()


def adjust(param, step):
    """Adjust a numeric parameter by step, respecting limits."""
    with _lock:
        if param not in LIMITS:
            return _settings.get(param)
        lo, hi = LIMITS[param]
        _settings[param] = max(lo, min(hi, _settings[param] + step))
        val = _settings[param]
        _save_locked()
    return val
