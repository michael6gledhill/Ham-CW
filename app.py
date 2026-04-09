#!/usr/bin/env python3
"""ham-cw: Iambic CW keyer with Flask web interface.

Reads three SPDT switches and two iambic paddles, generates accurate
Morse code audio, and provides a web-based settings interface.

GPIO uses gpiozero with pigpio pin factory for DMA-quality PWM.
"""

import logging
import os
import signal
import threading
import time

from flask import Flask, render_template, jsonify, request

import settings
from morse import Keyer, text_to_elements
from audio import AudioEngine

# ---------------------------------------------------------------------------
#  GPIO setup (gpiozero with pigpio factory for DMA PWM)
# ---------------------------------------------------------------------------
HAS_GPIO = False
try:
    from gpiozero import Device, Button, PWMOutputDevice, OutputDevice
    try:
        from gpiozero.pins.pigpio import PiGPIOFactory
        Device.pin_factory = PiGPIOFactory()
        print("morse-keyer: using pigpio pin factory (DMA PWM)")
    except Exception:
        print("morse-keyer: pigpio factory unavailable, using default")
    HAS_GPIO = True
except ImportError:
    print("morse-keyer: gpiozero not available -- GPIO disabled")

# ---------------------------------------------------------------------------
#  Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

# Minimize logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
#  Shared state
# ---------------------------------------------------------------------------
class State:
    key_down = False
    dit = False
    dah = False
    mode = 'transmit'       # 'transmit' or 'settings'
    sending = False
    config_mode = False
    config_awaiting = None  # role name being auto-detected
    config_detected = None  # GPIO pin number when detected

state = State()

# GPIO device objects keyed by role name
_gpio_devs = {}
_gpio_lock = threading.Lock()

# Audio engine
audio = AudioEngine()

# Keyer
keyer = Keyer()

# Send queue
_send_queue = []
_sq_lock = threading.Lock()

# Shutdown
_shutdown = threading.Event()

# ---------------------------------------------------------------------------
#  GPIO management
# ---------------------------------------------------------------------------
def _close_gpio():
    """Close all gpiozero device objects."""
    with _gpio_lock:
        for dev in _gpio_devs.values():
            try:
                dev.close()
            except Exception:
                pass
        _gpio_devs.clear()


def setup_gpio():
    """Create gpiozero device objects from current settings."""
    _close_gpio()
    if not HAS_GPIO:
        return

    cfg = settings.get()

    with _gpio_lock:
        try:
            # Input pins (pull-up, active when grounded)
            for role in ('pin_freq_up', 'pin_freq_down',
                         'pin_speed_up', 'pin_speed_down',
                         'pin_settings', 'pin_dot', 'pin_dash'):
                pin = cfg.get(role, 0)
                if 2 <= pin <= 27:
                    _gpio_devs[role] = Button(pin, pull_up=True)

            # Speaker PWM output
            pin_spk = cfg.get('pin_speaker_1', 0)
            if 2 <= pin_spk <= 27:
                _gpio_devs['pin_speaker_1'] = PWMOutputDevice(
                    pin_spk, frequency=cfg['frequency'])

            # Speaker ground (tied LOW)
            pin_gnd = cfg.get('pin_speaker_2', 0)
            if 2 <= pin_gnd <= 27:
                _gpio_devs['pin_speaker_2'] = OutputDevice(
                    pin_gnd, initial_value=False)

        except Exception as e:
            print(f"morse-keyer: GPIO setup error: {e}")


def _read_pin(role):
    """Read a button-type GPIO. Returns True when grounded."""
    with _gpio_lock:
        dev = _gpio_devs.get(role)
    if dev and hasattr(dev, 'is_pressed'):
        try:
            return dev.is_pressed
        except Exception:
            pass
    return False


def _speaker_on(freq):
    with _gpio_lock:
        dev = _gpio_devs.get('pin_speaker_1')
    if dev:
        try:
            dev.frequency = max(1, int(freq))
            dev.value = 0.5
        except Exception:
            pass


def _speaker_off():
    with _gpio_lock:
        dev = _gpio_devs.get('pin_speaker_1')
    if dev:
        try:
            dev.value = 0
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  Send queue
# ---------------------------------------------------------------------------
def _enqueue(elements):
    with _sq_lock:
        _send_queue.clear()
        _send_queue.extend(elements)


def _stop_send():
    with _sq_lock:
        _send_queue.clear()


def _enqueue_text(text):
    cfg = settings.get()
    els = text_to_elements(text.strip(), cfg['wpm'])
    if els:
        _enqueue(els)


def _enqueue_test():
    _enqueue([('on', 0.5)])


# ---------------------------------------------------------------------------
#  Switch polling thread (50 Hz)
# ---------------------------------------------------------------------------
_prev_sw = {}


def _switch_poll_loop():
    """Poll SPDT switches at 50 Hz with edge detection."""
    global _prev_sw

    while not _shutdown.is_set():
        if state.config_mode:
            time.sleep(0.1)
            continue

        cfg = settings.get()

        # Settings toggle (state-based, not edge)
        state.mode = 'settings' if _read_pin('pin_settings') else 'transmit'

        # Edge-detected adjustments
        for role, param, step in (
            ('pin_freq_up',    'frequency',  10),
            ('pin_freq_down',  'frequency', -10),
            ('pin_speed_up',   'wpm',         1),
            ('pin_speed_down', 'wpm',        -1),
        ):
            cur = _read_pin(role)
            prev = _prev_sw.get(role, False)
            if cur and not prev:
                val = settings.adjust(param, step)
                if param == 'frequency' and val is not None:
                    audio.set_frequency(val)
            _prev_sw[role] = cur

        time.sleep(0.02)  # 50 Hz


# ---------------------------------------------------------------------------
#  Keyer loop (1 ms tick -- paddles need <10 ms latency)
# ---------------------------------------------------------------------------
def _keyer_loop():
    dt = 0.001
    sq_action = None
    sq_end = 0.0

    while not _shutdown.is_set():
        t0 = time.monotonic()
        cfg = settings.get()
        keyer.update(cfg['wpm'])

        # Read paddles
        dit = _read_pin('pin_dot')
        dah = _read_pin('pin_dash')
        state.dit = dit
        state.dah = dah

        # Paddle press cancels text send
        if (dit or dah) and _send_queue:
            _stop_send()
            sq_action = None

        # Process send queue
        now = time.monotonic()
        if sq_action is not None and now >= sq_end:
            sq_action = None
        if sq_action is None:
            with _sq_lock:
                if _send_queue:
                    act, dur = _send_queue.pop(0)
                    sq_action = act
                    sq_end = now + dur

        state.sending = sq_action is not None or bool(_send_queue)

        # Key state
        key_down = False
        if state.mode == 'transmit':
            if sq_action is not None:
                key_down = (sq_action == 'on')
            else:
                key_down = keyer.tick(dt, dit, dah)
        else:
            # Settings mode -- still allow test tones from send queue
            if sq_action is not None:
                key_down = (sq_action == 'on')

        # Drive speaker + audio engine
        if key_down != state.key_down:
            state.key_down = key_down
            if key_down:
                _speaker_on(cfg['frequency'])
                audio.key_on()
            else:
                _speaker_off()
                audio.key_off()

        elapsed = time.monotonic() - t0
        remaining = dt - elapsed
        if remaining > 0:
            time.sleep(remaining)


# ---------------------------------------------------------------------------
#  GPIO auto-detection
# ---------------------------------------------------------------------------
def _start_config_mode(role):
    """Enter GPIO auto-detection mode for *role*."""
    state.config_mode = True
    state.config_awaiting = role
    state.config_detected = None

    # Close all GPIO so we can scan any pin
    _close_gpio()

    t = threading.Thread(target=_gpio_scan_loop, daemon=True,
                         name='gpio-scan')
    t.start()


def _stop_config_mode():
    """Cancel GPIO auto-detection."""
    state.config_mode = False
    state.config_awaiting = None
    time.sleep(0.15)   # let scan thread exit
    setup_gpio()


def _gpio_scan_loop():
    """Detect GPIO pin change using hardware edge callbacks (instant)."""
    if not HAS_GPIO:
        state.config_mode = False
        return

    from gpiozero import DigitalInputDevice

    cfg = settings.get()
    awaiting = state.config_awaiting

    # Pins already assigned to OTHER roles
    assigned = set()
    for role in settings.GPIO_PINS:
        if role != awaiting:
            pin = cfg.get(role, 0)
            if pin > 0:
                assigned.add(pin)

    candidates = [p for p in range(2, 28) if p not in assigned]

    # Event to signal detection from any callback
    detected_event = threading.Event()
    detected_pin = [None]

    def make_callback(pin_num):
        """Return a callback that records which pin fired."""
        def _cb():
            if detected_pin[0] is None:
                detected_pin[0] = pin_num
                detected_event.set()
        return _cb

    # Open all candidate pins with edge callbacks on BOTH edges
    scan_devs = []
    for pin in candidates:
        try:
            dev = DigitalInputDevice(pin, pull_up=True, bounce_time=0.04)
            cb = make_callback(pin)
            dev.when_activated = cb
            dev.when_deactivated = cb
            scan_devs.append(dev)
        except Exception:
            continue

    print(f"morse-keyer: edge-watching {len(scan_devs)} pins for {awaiting}")

    # Wait for any edge callback to fire (or cancellation)
    while state.config_mode and not _shutdown.is_set():
        if detected_event.wait(timeout=0.1):
            pin = detected_pin[0]
            if pin is not None:
                print(f"morse-keyer: detected GPIO {pin} for {awaiting}")
                state.config_detected = pin
                settings.update({awaiting: pin})
                state.config_mode = False
                state.config_awaiting = None
            break

    # Clean up all scan devices
    for dev in scan_devs:
        try:
            dev.when_activated = None
            dev.when_deactivated = None
            dev.close()
        except Exception:
            pass

    # Re-setup normal GPIO
    setup_gpio()


# ---------------------------------------------------------------------------
#  Flask routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/settings', methods=['GET'])
def get_settings():
    return jsonify(settings.get())


@app.route('/settings', methods=['POST'])
def update_settings():
    data = request.get_json(silent=True) or {}
    settings.update(data)
    # Apply frequency change to audio engine
    cfg = settings.get()
    audio.set_frequency(cfg['frequency'])
    return jsonify({'ok': True})


@app.route('/save-settings', methods=['POST'])
def save_settings():
    settings.save()
    return jsonify({'ok': True})


@app.route('/gpio-status', methods=['GET'])
def gpio_status():
    return jsonify({
        'mode':     state.mode,
        'dit':      state.dit,
        'dah':      state.dah,
        'key_down': state.key_down,
        'sending':  state.sending,
    })


@app.route('/start-config-mode', methods=['POST'])
def start_config_mode():
    data = request.get_json(silent=True) or {}
    role = data.get('role', '')
    if role not in settings.AUTO_DETECT_PINS:
        return jsonify({'error': 'invalid role'}), 400
    _start_config_mode(role)
    return jsonify({'ok': True})


@app.route('/stop-config-mode', methods=['POST'])
def stop_config_mode():
    _stop_config_mode()
    return jsonify({'ok': True})


@app.route('/config-status', methods=['GET'])
def config_status():
    return jsonify({
        'config_mode': state.config_mode,
        'awaiting':    state.config_awaiting,
        'detected':    state.config_detected,
    })


# -- Extra convenience endpoints for the web UI --

@app.route('/api/adjust', methods=['POST'])
def api_adjust():
    data = request.get_json(silent=True) or {}
    param = data.get('param', '')
    step = int(data.get('step', 0))
    if param not in settings.LIMITS or step == 0:
        return jsonify({'error': 'bad param or step'}), 400
    val = settings.adjust(param, step)
    if param == 'frequency':
        audio.set_frequency(val)
    return jsonify({'ok': True, 'value': val})


@app.route('/api/send', methods=['POST'])
def api_send():
    data = request.get_json(silent=True) or {}
    text = str(data.get('text', '')).strip()
    if text:
        _enqueue_text(text)
    return jsonify({'ok': True})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    _stop_send()
    return jsonify({'ok': True})


@app.route('/api/test', methods=['POST'])
def api_test():
    _enqueue_test()
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------
def main():
    settings.load()
    cfg = settings.get()

    # GPIO
    setup_gpio()

    # Audio
    audio.set_frequency(cfg['frequency'])
    audio.start()

    # Keyer
    keyer.update(cfg['wpm'])

    # Background threads
    threading.Thread(target=_keyer_loop, daemon=True,
                     name='keyer-loop').start()
    threading.Thread(target=_switch_poll_loop, daemon=True,
                     name='switch-poll').start()

    signal.signal(signal.SIGTERM, lambda s, f: _shutdown.set())

    # Flask (blocks)
    try:
        app.run(host='0.0.0.0', port=80, debug=False,
                use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown.set()
        audio.stop()
        _close_gpio()
        print("morse-keyer: stopped")


if __name__ == '__main__':
    main()
