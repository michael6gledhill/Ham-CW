#!/usr/bin/env python3
"""ham-cw: Iambic CW keyer for Raspberry Pi 4.

Wires together:
    config          - persistent settings & pin mapping
    keyer_engine    - iambic Mode-B state machine
    gpio_handler    - paddle / switch inputs, PWM speaker, PTT output
    audio_engine    - ALSA sine-wave output to 3.5 mm TRRS
    gui             - tkinter touchscreen UI (optional)
"""

import os
import signal
import subprocess
import threading
import time

import config
from keyer_engine import Keyer, text_to_elements
from gpio_handler import GpioHandler
from audio_engine import AudioEngine

# ---------------------------------------------------------------------------
#  Shared application state (read by GUI, written by keyer loop)
# ---------------------------------------------------------------------------
class _State:
    key_down = False
    dit = False
    dah = False
    selected_param = 'wpm'

_state = _State()

# ---------------------------------------------------------------------------
#  Send queue (test tone, text CW, IP announce)
# ---------------------------------------------------------------------------
_send_queue = []
_sq_lock = threading.Lock()


def _enqueue(elements):
    with _sq_lock:
        _send_queue.clear()
        _send_queue.extend(elements)


def _enqueue_test():
    _enqueue([('on', 0.5)])


def _enqueue_text(text):
    cfg = config.get_config()
    els = text_to_elements(text, cfg['wpm'], cfg['weight'])
    if els:
        _enqueue(els)


def _enqueue_ip():
    try:
        ip = subprocess.check_output(
            ['hostname', '-I'], text=True, timeout=2
        ).split()[0]
    except Exception:
        ip = '0'
    cfg = config.get_config()
    els = text_to_elements(ip, cfg['wpm'], cfg['weight'])
    if els:
        _enqueue(els)


# ---------------------------------------------------------------------------
#  Public "app" interface consumed by the GUI
# ---------------------------------------------------------------------------
def get_config():
    return config.get_config()

selected_param = property(lambda self: _state.selected_param)
key_down = property(lambda self: _state.key_down)
dit = property(lambda self: _state.dit)
dah = property(lambda self: _state.dah)


class _App:
    """Thin facade so the GUI can call methods without knowing internals."""

    @property
    def selected_param(self):
        return _state.selected_param

    @property
    def key_down(self):
        return _state.key_down

    @property
    def dit(self):
        return _state.dit

    @property
    def dah(self):
        return _state.dah

    @staticmethod
    def get_config():
        return config.get_config()

    @staticmethod
    def select_param(name):
        if name in config.PARAMS:
            _state.selected_param = name

    @staticmethod
    def adjust(direction):
        val = config.adjust_param(_state.selected_param, direction)
        cfg = config.get_config()
        _audio.update(freq=cfg['freq'], volume=cfg['volume'])
        return val

    @staticmethod
    def test_tone():
        _enqueue_test()

    @staticmethod
    def send_text(text):
        _enqueue_text(text)


# ---------------------------------------------------------------------------
#  Switch callbacks (called from GPIO interrupt context)
# ---------------------------------------------------------------------------
def _on_switch_adjust(direction):
    """Physical Switch A flipped: adjust selected parameter."""
    config.adjust_param(_state.selected_param, direction)
    cfg = config.get_config()
    _audio.update(freq=cfg['freq'], volume=cfg['volume'])


def _on_switch_cycle():
    """Physical Switch B flipped: cycle to next parameter."""
    params = config.PARAMS
    idx = params.index(_state.selected_param) if _state.selected_param in params else 0
    _state.selected_param = params[(idx + 1) % len(params)]


# ---------------------------------------------------------------------------
#  Keyer loop (runs in its own thread)
# ---------------------------------------------------------------------------
_shutdown = threading.Event()


def _keyer_loop():
    """1 ms tick loop: reads paddles, runs keyer, drives outputs."""
    cfg = config.get_config()
    keyer = Keyer(cfg['wpm'], cfg['weight'])
    dt = 0.001               # 1 ms tick
    both_timer = 0.0
    sq_action = None
    sq_end = 0.0

    while not _shutdown.is_set():
        now = time.monotonic()
        cfg = config.get_config()
        keyer.update(cfg['wpm'], cfg['weight'])

        # -- read paddles ------------------------------------------------
        dit_pressed = _gpio.read_dit()
        dah_pressed = _gpio.read_dah()
        _state.dit = dit_pressed
        _state.dah = dah_pressed

        # -- poll parameter switches -------------------------------------
        _gpio.poll_switches()

        # -- hold both paddles 3 s -> announce IP ------------------------
        if dit_pressed and dah_pressed:
            both_timer += dt
            if both_timer >= 3.0:
                both_timer = 0.0
                _enqueue_ip()
        else:
            both_timer = 0.0

        # -- paddle press cancels text playback --------------------------
        if (dit_pressed or dah_pressed) and _send_queue:
            with _sq_lock:
                _send_queue.clear()
            sq_action = None

        # -- process send queue ------------------------------------------
        if sq_action is not None and now >= sq_end:
            sq_action = None
        if sq_action is None:
            with _sq_lock:
                if _send_queue:
                    act, dur = _send_queue.pop(0)
                    sq_action = act
                    sq_end = now + dur

        # -- determine key state -----------------------------------------
        if sq_action is not None:
            key_down = (sq_action == 'on')
        else:
            key_down = keyer.tick(dt, dit_pressed, dah_pressed)

        # -- update outputs on state change ------------------------------
        if key_down != _state.key_down:
            _state.key_down = key_down
            if key_down:
                _gpio.speaker_on(cfg['freq'])
                _audio.set_key(True)
                _gpio.set_ptt(True)
            else:
                _gpio.speaker_off()
                _audio.set_key(False)
                _gpio.set_ptt(False)

        # -- sleep remainder of tick -------------------------------------
        elapsed = time.monotonic() - now
        remaining = dt - elapsed
        if remaining > 0:
            time.sleep(remaining)


# ---------------------------------------------------------------------------
#  Module-level singletons (created early so callbacks can reference them)
# ---------------------------------------------------------------------------
_gpio = GpioHandler()
_audio = AudioEngine()


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------
def main():
    # Load config from disk
    config.load_config()
    cfg = config.get_config()

    # GPIO
    _gpio.on_adjust = _on_switch_adjust
    _gpio.on_cycle = _on_switch_cycle
    _gpio.setup(cfg)

    # Audio engine (ALSA)
    _audio.update(freq=cfg['freq'], volume=cfg['volume'])
    _audio.start()

    # Graceful shutdown on SIGINT / SIGTERM
    def _on_sig(_sig, _frame):
        _shutdown.set()
    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)

    # Start keyer thread
    kt = threading.Thread(target=_keyer_loop, daemon=True, name='keyer')
    kt.start()
    print('ham-cw: keyer running')

    # GUI (try to open regardless — let tkinter find the display)
    try:
        import tkinter as tk
        from gui import KeyerGui

        root = tk.Tk()
        KeyerGui(root, _App())
        print('ham-cw: GUI started')
        root.mainloop()              # blocks until window is closed
        _shutdown.set()
    except Exception as e:
        print(f'ham-cw: GUI unavailable ({e}), running headless')
        _shutdown.wait()

    # Cleanup
    _audio.stop()
    _gpio.speaker_off()
    _gpio.set_ptt(False)
    _gpio.cleanup()
    print('\nham-cw: stopped.')


if __name__ == '__main__':
    main()
