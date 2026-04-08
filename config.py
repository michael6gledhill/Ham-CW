"""Configuration for ham-cw keyer (Pi 4 + touchscreen).

Stores settings in config.json next to the application.
Thread-safe reads and writes.
"""

import json
import os
import threading

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'config.json')

DEFAULTS = {
    'wpm':         20,
    'freq':        700,
    'volume':      70,
    'freq_step':   50,
    'wpm_step':    1,
    'volume_step': 5,
    'pin_dit':      27,
    'pin_dah':      22,
    'pin_spk':      20,
    'pin_spk_gnd':  21,
    'pin_ptt':      16,
    'pin_mode':     26,
    'pin_sel':      13,
    'pin_adj_up':   5,
    'pin_adj_down': 6,
}

OUTPUT_PINS = {'pin_spk', 'pin_spk_gnd'}    # pin_ptt managed separately (hi-Z)

PARAMS = ['wpm', 'freq', 'volume']

LIMITS = {
    'wpm':    (5, 50),
    'freq':   (200, 2000),
    'volume': (0, 100),
}

STEPS = {
    'wpm':    'wpm_step',
    'freq':   'freq_step',
    'volume': 'volume_step',
}

_lock = threading.Lock()
_config = dict(DEFAULTS)
_selected = 0       # index into PARAMS


def load_config():
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
    with _lock:
        cfg = dict(_config)
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        print(f"ham-cw: failed to save config: {e}")


def get_config():
    with _lock:
        return dict(_config)


def update_config(updates):
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
    """Adjust *param* by its configured step in *direction* (+1 or -1)."""
    with _lock:
        step_key = STEPS.get(param)
        if not step_key:
            return _config.get(param)
        step = _config.get(step_key, 1)
        lo, hi = LIMITS[param]
        _config[param] = max(lo, min(hi, _config[param] + step * direction))
        val = _config[param]
    save_config()
    return val


def get_selected_param():
    with _lock:
        return PARAMS[_selected]


def cycle_selected_param():
    global _selected
    with _lock:
        _selected = (_selected + 1) % len(PARAMS)
        return PARAMS[_selected]


def set_selected_param(index):
    global _selected
    with _lock:
        _selected = index % len(PARAMS)
