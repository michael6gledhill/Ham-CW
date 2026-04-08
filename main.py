#!/usr/bin/env python3
"""ham-cw: Iambic CW keyer for Raspberry Pi 4.

Pi 4 with 7" touchscreen, ALSA audio to UV-5R radio via TRRS,
GPIO PWM sidetone speaker, wired-OR PTT logic.

Modes (selected by TX/Text SPDT switch):
    tx   - paddles drive keyer + speaker + ALSA; PTT via manual switch
    text - touchscreen text drives speaker + ALSA; PTT via GPIO (hi-Z / LOW)
"""

import signal
import subprocess
import threading
import time

import config
from keyer_engine import Keyer, text_to_elements
from gpio_handler import GpioHandler
from audio_engine import AudioEngine
from web_server import WebServer

WEIGHT = 300

# ---------------------------------------------------------------------------
#  Shared state (read by GUI, written by keyer loop)
# ---------------------------------------------------------------------------
class _State:
    key_down = False
    dit = False
    dah = False
    mode = 'tx'
    sending = False

_state = _State()

_gpio = GpioHandler()
_audio = AudioEngine()
_shutdown = threading.Event()

# ---------------------------------------------------------------------------
#  Send queue
# ---------------------------------------------------------------------------
_send_queue = []
_sq_lock = threading.Lock()


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
#  GPIO callbacks (run in pigpio callback thread)
# ---------------------------------------------------------------------------
def _on_param_cycle():
    config.cycle_selected_param()


def _on_param_adjust(direction):
    param = config.get_selected_param()
    config.adjust_param(param, direction)


# ---------------------------------------------------------------------------
#  GUI callbacks (run in tkinter main thread)
# ---------------------------------------------------------------------------
def _gui_adjust(param, direction):
    config.adjust_param(param, direction)


def _gui_select(index):
    config.set_selected_param(index)


def _gui_send(text):
    text = text.strip()
    if text:
        _enqueue_text(text)


def _gui_get_state():
    return {
        'mode': _state.mode,
        'dit': _state.dit,
        'dah': _state.dah,
        'key_down': _state.key_down,
        'sending': _state.sending,
    }


# ---------------------------------------------------------------------------
#  Web callbacks
# ---------------------------------------------------------------------------
def _web_update_config(updates):
    config.update_config(updates)
    cfg = config.get_config()
    _gpio.setup(cfg)


# ---------------------------------------------------------------------------
#  Keyer loop (background thread, 1 ms tick)
# ---------------------------------------------------------------------------
def _keyer_loop():
    cfg = config.get_config()
    keyer = Keyer(cfg['wpm'], WEIGHT)
    dt = 0.001

    both_timer = 0.0
    sq_action = None
    sq_end = 0.0
    prev_mode = None
    last_freq = cfg['freq']
    last_volume = cfg['volume']

    while not _shutdown.is_set():
        now = time.monotonic()
        cfg = config.get_config()
        keyer.update(cfg['wpm'], WEIGHT)

        # -- mode ----------------------------------------------------------
        mode = _gpio.read_mode()
        _state.mode = mode

        # Reset keyer on mode transition into tx
        if mode != prev_mode:
            if mode == 'tx':
                keyer.reset()
            prev_mode = mode

        # -- paddles -------------------------------------------------------
        dit_pressed = _gpio.read_dit()
        dah_pressed = _gpio.read_dah()
        _state.dit = dit_pressed
        _state.dah = dah_pressed

        # Hold both paddles 3 s -> announce IP
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

        # -- send queue ----------------------------------------------------
        if sq_action is not None and now >= sq_end:
            sq_action = None
        if sq_action is None:
            with _sq_lock:
                if _send_queue:
                    act, dur = _send_queue.pop(0)
                    sq_action = act
                    sq_end = now + dur

        sending = sq_action is not None or bool(_send_queue)
        _state.sending = sending

        # -- key state -----------------------------------------------------
        key_down = False

        if mode == 'tx':
            if sq_action is not None:
                key_down = (sq_action == 'on')
            else:
                key_down = keyer.tick(dt, dit_pressed, dah_pressed)
        elif mode == 'text':
            key_down = (sq_action == 'on') if sq_action is not None else False

        # -- speaker + ALSA ------------------------------------------------
        if key_down != _state.key_down:
            _state.key_down = key_down
            if key_down:
                _gpio.speaker_on(cfg['freq'])
                _audio.set_key(True)
            else:
                _gpio.speaker_off()
                _audio.set_key(False)

        # Update audio params on change
        if cfg['freq'] != last_freq:
            _audio.set_freq(cfg['freq'])
            last_freq = cfg['freq']
        if cfg['volume'] != last_volume:
            _audio.set_volume(cfg['volume'])
            last_volume = cfg['volume']

        # -- PTT (text mode only: hi-Z <-> OUTPUT LOW) --------------------
        if mode == 'text':
            _gpio.set_ptt(sending)
        else:
            _gpio.set_ptt(False)

        # -- tick sleep ----------------------------------------------------
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
    _gpio.on_param_cycle = _on_param_cycle
    _gpio.on_param_adjust = _on_param_adjust
    _gpio.setup(cfg)

    # Audio engine
    _audio.set_freq(cfg['freq'])
    _audio.set_volume(cfg['volume'])
    _audio.start()

    # Web server (background thread)
    web = WebServer(
        get_status=_gui_get_state,
        get_config=config.get_config,
        update_config=_web_update_config,
        adjust_param=config.adjust_param,
        send_text=_enqueue_text,
        stop_send=_stop_send,
        test_tone=_enqueue_test,
        scan_pins=_gpio.scan_pins,
        port=80,
    )
    try:
        web.start()
    except Exception as e:
        print(f"ham-cw: web server failed to start: {e}")

    # Keyer loop (background thread)
    keyer_thread = threading.Thread(target=_keyer_loop, daemon=True,
                                    name='keyer-loop')
    keyer_thread.start()

    # GUI (main thread -- tkinter requirement)
    try:
        import tkinter as tk
        from gui import Gui

        root = tk.Tk()
        _gui = Gui(root,
                   on_adjust=_gui_adjust,
                   on_select=_gui_select,
                   on_send=_gui_send,
                   on_stop=_stop_send,
                   on_test=_enqueue_test,
                   get_state=_gui_get_state)

        def _on_close():
            _shutdown.set()
            web.stop()
            _audio.stop()
            _gpio.cleanup()
            root.destroy()

        root.protocol('WM_DELETE_WINDOW', _on_close)

        # Poll for SIGTERM shutdown
        def _check_shutdown():
            if _shutdown.is_set():
                _on_close()
            else:
                root.after(200, _check_shutdown)
        root.after(200, _check_shutdown)

        signal.signal(signal.SIGTERM, lambda s, f: _shutdown.set())

        root.mainloop()

    except (ImportError, Exception) as e:
        # Headless fallback (no display or no tkinter)
        print(f"ham-cw: no GUI -- headless mode ({e})")
        signal.signal(signal.SIGINT, lambda s, f: _shutdown.set())
        signal.signal(signal.SIGTERM, lambda s, f: _shutdown.set())
        try:
            while not _shutdown.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            _shutdown.set()

    web.stop()
    _audio.stop()
    _gpio.cleanup()
    print("ham-cw: stopped")


if __name__ == '__main__':
    main()
