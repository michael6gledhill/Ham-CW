#!/usr/bin/env python3
"""ham-cw: Iambic CW keyer for Raspberry Pi Zero.

Wires together:
    config       - persistent settings & pin mapping
    keyer_engine - iambic Mode-B state machine
    gpio_handler - paddle/switch inputs, PWM speaker, TX output
    web_server   - HTTP web interface
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
#  Shared state (read by web API, written by keyer loop)
# ---------------------------------------------------------------------------
class _State:
    key_down = False
    dit = False
    dah = False
    mode = 'paddle'
    sending = False

_state = _State()

# ---------------------------------------------------------------------------
#  Module-level singletons
# ---------------------------------------------------------------------------
_gpio = GpioHandler()
_shutdown = threading.Event()

# ---------------------------------------------------------------------------
#  Send queue
# ---------------------------------------------------------------------------
_send_queue = []
_sq_lock = threading.Lock()

WEIGHT = 300    # standard 3:1 dah/dit ratio


def _enqueue(elements):
    with _sq_lock:
        _send_queue.clear()
        _send_queue.extend(elements)


def _enqueue_test():
    _enqueue([('on', 0.5)])


def _enqueue_text(text):
    cfg = config.get_config()
    els = text_to_elements(text, cfg['wpm'], WEIGHT)
    if els:
        _enqueue(els)


def _stop_send():
    with _sq_lock:
        _send_queue.clear()


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


def _web_send_text(text):
    if not text:
        _stop_send()
    else:
        _enqueue_text(text)


# ---------------------------------------------------------------------------
#  GPIO switch callbacks
# ---------------------------------------------------------------------------
def _on_tone_adjust(direction):
    config.adjust_param('freq', direction)


def _on_wpm_adjust(direction):
    config.adjust_param('wpm', direction)


# ---------------------------------------------------------------------------
#  Keyer loop (runs in its own thread)
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

        # -- read mode switch --------------------------------------------
        _state.mode = _gpio.read_mode()

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

        _state.sending = sq_action is not None or bool(_send_queue)

        # -- determine key state -----------------------------------------
        if _state.mode == 'text':
            # Text mode: only send queue drives keying
            key_down = (sq_action == 'on') if sq_action is not None else False
        else:
            # Paddle mode: paddles + send queue (test tone)
            if sq_action is not None:
                key_down = (sq_action == 'on')
            else:
                key_down = keyer.tick(dt, dit_pressed, dah_pressed)

        # -- update speaker on state change ------------------------------
        if key_down != _state.key_down:
            _state.key_down = key_down
            if key_down:
                _gpio.speaker_on(cfg['freq'])
            else:
                _gpio.speaker_off()

        # -- TX output: ground pin only in text mode ---------------------
        _gpio.set_tx(key_down and _state.mode == 'text')

        # -- sleep remainder of tick -------------------------------------
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

    # GPIO
    _gpio.on_tone_adjust = _on_tone_adjust
    _gpio.on_wpm_adjust = _on_wpm_adjust
    _gpio.setup(cfg)

    # Web server
    web = WebServer(
        get_status=_get_status,
        get_config=config.get_config,
        update_config=_update_config,
        send_text=_web_send_text,
        test_tone=_enqueue_test,
        port=80,
    )
    web.start()

    # Keyer loop in background thread
    keyer_thread = threading.Thread(target=_keyer_loop, daemon=True,
                                    name='keyer-loop')
    keyer_thread.start()

    # Graceful shutdown
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
