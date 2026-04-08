"""GPIO handler using pigpio (DMA-timed PWM).

pigpio produces rock-solid PWM via DMA, eliminating the jitter and
terrible audio quality of RPi.GPIO's software PWM.

Requires the pigpio daemon: sudo systemctl enable pigpiod
"""

import time

try:
    import pigpio
    _pi = pigpio.pi()
    HAS_GPIO = _pi.connected
except Exception:
    pigpio = None
    _pi = None
    HAS_GPIO = False

_SW_DEBOUNCE = 0.25     # seconds


class GpioHandler:
    """Set up and interact with all GPIO pins via pigpio."""

    def __init__(self):
        self._pins = {}
        self._tone_on = False
        self.on_tone_adjust = None
        self.on_wpm_adjust = None

        self._tone_up_last = False
        self._tone_down_last = False
        self._wpm_up_last = False
        self._wpm_down_last = False
        self._tone_up_time = 0.0
        self._tone_down_time = 0.0
        self._wpm_up_time = 0.0
        self._wpm_down_time = 0.0

    def setup(self, cfg):
        """Configure all GPIO pins from *cfg* dict."""
        self.speaker_off()
        self._pins = {k: v for k, v in cfg.items() if k.startswith('pin_')}

        if not HAS_GPIO:
            return

        # Inputs (pull-up, active low)
        for key in ('pin_dit', 'pin_dah', 'pin_mode_text', 'pin_mode_tx',
                     'pin_tone_up', 'pin_tone_down',
                     'pin_wpm_up', 'pin_wpm_down'):
            _pi.set_mode(self._pins[key], pigpio.INPUT)
            _pi.set_pull_up_down(self._pins[key], pigpio.PUD_UP)

        # Speaker output
        _pi.set_mode(self._pins['pin_spk'], pigpio.OUTPUT)
        _pi.write(self._pins['pin_spk'], 0)

        # Speaker ground (tie low)
        _pi.set_mode(self._pins['pin_spk_gnd'], pigpio.OUTPUT)
        _pi.write(self._pins['pin_spk_gnd'], 0)

        # Text-mode ground pin (default high = not grounded)
        _pi.set_mode(self._pins['pin_text_ground'], pigpio.OUTPUT)
        _pi.write(self._pins['pin_text_ground'], 1)

        self._tone_up_last = self._read('pin_tone_up')
        self._tone_down_last = self._read('pin_tone_down')
        self._wpm_up_last = self._read('pin_wpm_up')
        self._wpm_down_last = self._read('pin_wpm_down')

    def cleanup(self):
        self.speaker_off()
        if HAS_GPIO and _pi.connected:
            # Leave pins in a safe state but don't disconnect — daemon
            # stays running for next launch.
            try:
                _pi.write(self._pins.get('pin_text_ground', 0), 1)
            except Exception:
                pass

    # -- input reads ------------------------------------------------------

    def _read(self, key):
        if not HAS_GPIO:
            return False
        try:
            return _pi.read(self._pins[key]) == 0
        except Exception:
            return False

    def read_dit(self):
        return self._read('pin_dit')

    def read_dah(self):
        return self._read('pin_dah')

    def read_mode(self):
        if self._read('pin_mode_text'):
            return 'text'
        if self._read('pin_mode_tx'):
            return 'tx'
        return 'idle'

    # -- pin scanning (for Detect feature) --------------------------------

    def scan_pins(self):
        if not HAS_GPIO:
            return []

        from config import OUTPUT_PINS
        output_nums = set()
        for key in OUTPUT_PINS:
            if key in self._pins:
                output_nums.add(self._pins[key])

        active = []
        for pin in range(2, 28):
            if pin in output_nums:
                continue
            try:
                _pi.set_mode(pin, pigpio.INPUT)
                _pi.set_pull_up_down(pin, pigpio.PUD_UP)
                if _pi.read(pin) == 0:
                    active.append(pin)
            except Exception:
                continue
        return active

    # -- switch polling ---------------------------------------------------

    def poll_switches(self):
        now = time.monotonic()

        cur = self._read('pin_tone_up')
        if cur and not self._tone_up_last and (now - self._tone_up_time) > _SW_DEBOUNCE:
            self._tone_up_time = now
            if self.on_tone_adjust:
                self.on_tone_adjust(1)
        self._tone_up_last = cur

        cur = self._read('pin_tone_down')
        if cur and not self._tone_down_last and (now - self._tone_down_time) > _SW_DEBOUNCE:
            self._tone_down_time = now
            if self.on_tone_adjust:
                self.on_tone_adjust(-1)
        self._tone_down_last = cur

        cur = self._read('pin_wpm_up')
        if cur and not self._wpm_up_last and (now - self._wpm_up_time) > _SW_DEBOUNCE:
            self._wpm_up_time = now
            if self.on_wpm_adjust:
                self.on_wpm_adjust(1)
        self._wpm_up_last = cur

        cur = self._read('pin_wpm_down')
        if cur and not self._wpm_down_last and (now - self._wpm_down_time) > _SW_DEBOUNCE:
            self._wpm_down_time = now
            if self.on_wpm_adjust:
                self.on_wpm_adjust(-1)
        self._wpm_down_last = cur

    # -- speaker (DMA-timed PWM via pigpio) -------------------------------

    def speaker_on(self, freq):
        """Start or update tone.  pigpio DMA PWM — clean, jitter-free."""
        if not HAS_GPIO:
            return
        pin = self._pins['pin_spk']
        freq = max(1, min(40000, int(freq)))
        try:
            _pi.set_PWM_frequency(pin, freq)
            _pi.set_PWM_dutycycle(pin, 128)   # 50% of 0-255 range
            self._tone_on = True
        except Exception:
            pass

    def speaker_off(self):
        if not HAS_GPIO or not self._tone_on:
            return
        try:
            _pi.set_PWM_dutycycle(self._pins['pin_spk'], 0)
        except Exception:
            pass
        self._tone_on = False

    # -- text-mode ground pin ---------------------------------------------

    def set_text_ground(self, active):
        if not HAS_GPIO:
            return
        try:
            _pi.write(self._pins['pin_text_ground'], 0 if active else 1)
        except Exception:
            pass
