#!/usr/bin/env python3
"""ham-cw: Iambic CW keyer for Raspberry Pi Zero.

Modes (selected by two SPDT switches):
    idle  - neither mode switch active; no keying
    tx    - paddle mode; paddles drive keyer + speaker
    text  - text mode; web UI text drives speaker + grounds pin_text_ground
"""

import signal
import subprocess
import threading
import time

import config
from keyer_engine import Keyer, text_to_elements
from gpio_handler import GpioHandler
from web_server import WebServer

# ---------------------------------------------------------------------------
#  Shared state
# ---------------------------------------------------------------------------
class _State:
    key_down = False
    dit = False
    dah = False
    mode = 'idle'
    sending = False

_state = _State()

_gpio = GpioHandler()
_shutdown = threading.Event()

# ---------------------------------------------------------------------------
#  Send queue
# ---------------------------------------------------------------------------
_send_queue = []
_sq_lock = threading.Lock()
WEIGHT = 300


def _enqueue(elements):
    with _sq_lock:
        _send_queue.clear()
        _send_queue.extend(elements)


def _stop_send():
    with _sq_lock:
        _send_queue.clear()


def _enqueue_test():
    _enqueue([('on', 0.5)])


def _enqueue_text(text):
    cfg = config.get_config()
    els = text_to_elements(text, cfg['wpm'], WEIGHT)
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
    els = text_to_elements(ip, cfg['wpm'], WEIGHT)
    if els:
        _enqueue(els)


# ---------------------------------------------------------------------------
#  Web API callbacks
# ---------------------------------------------------------------------------
def _get_status():
    cfg = config.get_config()
    return {
        'wpm': cfg['wpm'],
        'freq': cfg['freq'],
        'freq_step': cfg['freq_step'],
        'wpm_step': cfg['wpm_step'],
        'mode': _state.mode,
        'dit': _state.dit,
        'dah': _state.dah,
        'key_down': _state.key_down,
        'sending': _state.sending,
    }


def _update_config(updates):
    config.update_config(updates)
    cfg = config.get_config()
    _gpio.setup(cfg)


def _on_tone_adjust(direction):
    config.adjust_param('freq', direction)


def _on_wpm_adjust(direction):
    config.adjust_param('wpm', direction)


# ---------------------------------------------------------------------------
#  Keyer loop
# ---------------------------------------------------------------------------
def _keyer_loop():
    cfg = config.get_config()
    keyer = Keyer(cfg['wpm'], WEIGHT)
    dt = 0.001
    both_timer = 0.0
    sq_action = None
    sq_end = 0.0

    while not _shutdown.is_set():
        now = time.monotonic()
        cfg = config.get_config()
        keyer.update(cfg['wpm'], WEIGHT)

        _state.mode = _gpio.read_mode()

        dit_pressed = _gpio.read_dit()
        dah_pressed = _gpio.read_dah()
        _state.dit = dit_pressed
        _state.dah = dah_pressed

        _gpio.poll_switches()

        # Hold both paddles 3s -> announce IP
        if dit_pressed and dah_pressed:
            both_timer += dt
            if both_timer >= 3.0:
                both_timer = 0.0
                _enqueue_ip()
        else:
            both_timer = 0.0

        # Paddle press cancels text playback
        if (dit_pressed or dah_pressed) and _send_queue:
            _stop_send()
            sq_action = None

        # Process send queue
        if sq_action is not None and now >= sq_end:
            sq_action = None
        if sq_action is None:
            with _sq_lock:
                if _send_queue:
                    act, dur = _send_queue.pop(0)
                    sq_action = act
                    sq_end = now + dur

        _state.sending = sq_action is not None or bool(_send_queue)

        # Determine key state
        key_down = False

        if _state.mode == 'tx':
            if sq_action is not None:
                key_down = (sq_action == 'on')
            else:
                key_down = keyer.tick(dt, dit_pressed, dah_pressed)

        elif _state.mode == 'text':
            key_down = (sq_action == 'on') if sq_action is not None else False

        else:
            # Idle: test tone still works
            if sq_action is not None:
                key_down = (sq_action == 'on')

        # Speaker
        if key_down != _state.key_down:
            _state.key_down = key_down
            if key_down:
                _gpio.speaker_on(cfg['freq'])
            else:
                _gpio.speaker_off()

        # Ground text pin for entire transmission, not per-element
        _gpio.set_text_ground(_state.sending and _state.mode == 'text')

        elapsed = time.monotonic() - now
        remaining = dt - elapsed
        if remaining > 0:
            time.sleep(remaining)


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------
def main():
    config.load_config()
    cfg = config.get_config()

    _gpio.on_tone_adjust = _on_tone_adjust
    _gpio.on_wpm_adjust = _on_wpm_adjust
    _gpio.setup(cfg)

    web = WebServer(
        get_status=_get_status,
        get_config=config.get_config,
        update_config=_update_config,
        send_text=_enqueue_text,
        stop_send=_stop_send,
        test_tone=_enqueue_test,
        scan_pins=_gpio.scan_pins,
        port=80,
    )
    web.start()

    keyer_thread = threading.Thread(target=_keyer_loop, daemon=True,
                                    name='keyer-loop')
    keyer_thread.start()

    def _on_sig(_sig, _frame):
        _shutdown.set()
    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)

    try:
        while not _shutdown.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown.set()

    web.stop()
    _gpio.cleanup()
    print("ham-cw: stopped")


if __name__ == '__main__':
    main()
