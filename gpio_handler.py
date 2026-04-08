"""GPIO handler for ham-cw keyer.

Manages paddle/switch inputs with polled software debounce,
PWM sidetone speaker, and TX output pin.

Note: RPi.GPIO add_event_detect is broken on Pi OS kernels >= 6.x.
All inputs are polled from the keyer loop.
"""

import time

try:
    import RPi.GPIO as IO
    HAS_GPIO = True
except ImportError:
    IO = None
    HAS_GPIO = False

_SW_DEBOUNCE = 0.25     # seconds — parameter switches


class GpioHandler:
    """Set up and interact with all GPIO pins."""

    def __init__(self):
        self._pwm = None
        self._pwm_pin = -1
        self._pins = {}
        self.on_tone_adjust = None     # callback(direction: +1/-1)
        self.on_wpm_adjust = None      # callback(direction: +1/-1)

        # Debounce state
        self._tone_up_last = False
        self._tone_down_last = False
        self._wpm_up_last = False
        self._wpm_down_last = False
        self._tone_up_time = 0.0
        self._tone_down_time = 0.0
        self._wpm_up_time = 0.0
        self._wpm_down_time = 0.0

    # -- setup / teardown -------------------------------------------------

    def setup(self, cfg):
        """Configure all GPIO pins from *cfg* dict."""
        self.cleanup()
        self._pins = {k: v for k, v in cfg.items() if k.startswith('pin_')}

        if not HAS_GPIO:
            return

        IO.setmode(IO.BCM)
        IO.setwarnings(False)

        # Inputs (active-low with internal pull-ups)
        for key in ('pin_dit', 'pin_dah', 'pin_mode_text', 'pin_mode_tx',
                     'pin_tone_up', 'pin_tone_down',
                     'pin_wpm_up', 'pin_wpm_down'):
            IO.setup(self._pins[key], IO.IN, pull_up_down=IO.PUD_UP)

        # Outputs
        IO.setup(self._pins['pin_spk'], IO.OUT, initial=IO.LOW)
        IO.setup(self._pins['pin_spk_gnd'], IO.OUT, initial=IO.LOW)
        IO.setup(self._pins['pin_text_ground'], IO.OUT, initial=IO.HIGH)

        # Initialise debounce state
        self._tone_up_last = self._read('pin_tone_up')
        self._tone_down_last = self._read('pin_tone_down')
        self._wpm_up_last = self._read('pin_wpm_up')
        self._wpm_down_last = self._read('pin_wpm_down')

    def cleanup(self):
        self.speaker_off()
        if HAS_GPIO:
            try:
                IO.cleanup()
            except Exception:
                pass

    # -- input reads ------------------------------------------------------

    def _read(self, key):
        """Read a pin by config key name.  Returns True when active (low)."""
        if not HAS_GPIO:
            return False
        try:
            return IO.input(self._pins[key]) == 0
        except Exception:
            return False

    def read_dit(self):
        return self._read('pin_dit')

    def read_dah(self):
        return self._read('pin_dah')

    def read_mode(self):
        """Returns 'text', 'tx', or 'idle'."""
        if self._read('pin_mode_text'):
            return 'text'
        if self._read('pin_mode_tx'):
            return 'tx'
        return 'idle'

    # -- GPIO pin scanning (for detect feature) ---------------------------

    def scan_pins(self):
        """Scan GPIO 2-27 for active (low) pins.
        Skips pins currently configured as outputs.
        Returns list of active pin numbers."""
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
                IO.setup(pin, IO.IN, pull_up_down=IO.PUD_UP)
                if IO.input(pin) == 0:
                    active.append(pin)
            except Exception:
                continue
        return active

    # -- switch polling ---------------------------------------------------

    def poll_switches(self):
        """Call every tick from keyer loop."""
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

    # -- speaker (software PWM) -------------------------------------------

    def speaker_on(self, freq):
        """Start or update the PWM sidetone at *freq* Hz (50% duty)."""
        if not HAS_GPIO:
            return
        pin = self._pins['pin_spk']

        if self._pwm is not None and self._pwm_pin == pin:
            try:
                self._pwm.ChangeFrequency(max(1, freq))
                return
            except Exception:
                self._pwm = None

        self.speaker_off()
        try:
            self._pwm = IO.PWM(pin, max(1, freq))
            self._pwm.start(50)
            self._pwm_pin = pin
        except Exception:
            self._pwm = None

    def speaker_off(self):
        if self._pwm:
            try:
                self._pwm.stop()
            except Exception:
                pass
            self._pwm = None
            self._pwm_pin = -1

    # -- TX output --------------------------------------------------------

    def set_text_ground(self, active):
        """Ground pin_text_ground when *active* (keying in text mode)."""
        if not HAS_GPIO:
            return
        try:
            IO.output(self._pins['pin_text_ground'],
                      IO.LOW if active else IO.HIGH)
        except Exception:
            pass
