"""GPIO handler for ham-cw keyer.

Manages paddle/switch inputs with polled software debounce,
PWM sidetone speaker, and PTT output.  Falls back to stubs
when RPi.GPIO is unavailable (desktop testing).

Note: RPi.GPIO add_event_detect is broken on Pi OS kernels >= 6.x
(gpiochip interface).  All inputs are polled from the keyer loop
instead, which runs at 1 ms — plenty fast for debounce.
"""

import time

try:
    import RPi.GPIO as IO
    HAS_GPIO = True
except ImportError:
    IO = None
    HAS_GPIO = False

# Debounce hold-off (seconds)
_SW_DEBOUNCE = 0.25         # parameter switches
_PADDLE_DEBOUNCE = 0.005    # paddles (not used directly — keyer handles)


class GpioHandler:
    """Set up and interact with all GPIO pins."""

    def __init__(self):
        self._pwm = None
        self._pwm_pin = -1
        self._pins = {}
        self.on_adjust = None      # callback(direction: +1/-1)
        self.on_cycle = None       # callback()

        # Switch debounce state
        self._sw_up_last = False
        self._sw_down_last = False
        self._sw_sel_last = False
        self._sw_up_time = 0.0
        self._sw_down_time = 0.0
        self._sw_sel_time = 0.0

    # -- setup / teardown -------------------------------------------------

    def setup(self, cfg):
        """Configure all GPIO pins from *cfg* dict."""
        self.cleanup()
        self._pins = {k: v for k, v in cfg.items() if k.startswith("pin_")}

        if not HAS_GPIO:
            return

        IO.setmode(IO.BCM)
        IO.setwarnings(False)

        # Inputs (active-low with internal pull-ups)
        for key in ("pin_dit", "pin_dah", "pin_sw_up",
                     "pin_sw_down", "pin_sw_sel"):
            IO.setup(self._pins[key], IO.IN, pull_up_down=IO.PUD_UP)

        # Outputs
        IO.setup(self._pins["pin_spk"], IO.OUT, initial=IO.LOW)
        IO.setup(self._pins["pin_spk_gnd"], IO.OUT, initial=IO.LOW)
        IO.setup(self._pins["pin_ptt"], IO.OUT, initial=IO.LOW)

        # Read initial switch state so first poll doesn't false-trigger
        self._sw_up_last = self._read("pin_sw_up")
        self._sw_down_last = self._read("pin_sw_down")
        self._sw_sel_last = self._read("pin_sw_sel")

    def cleanup(self):
        """Release GPIO resources."""
        self.speaker_off()
        if HAS_GPIO:
            try:
                IO.cleanup()
            except Exception:
                pass

    # -- input reads ------------------------------------------------------

    def _read(self, key):
        """Read a pin by config key name. Returns True when active (low)."""
        if not HAS_GPIO:
            return False
        return IO.input(self._pins[key]) == 0

    def read_dit(self):
        return self._read("pin_dit")

    def read_dah(self):
        return self._read("pin_dah")

    def poll_switches(self):
        """Call every tick from keyer loop.  Fires on_adjust / on_cycle
        callbacks on debounced switch transitions."""
        now = time.monotonic()

        # Switch A — Up
        cur = self._read("pin_sw_up")
        if cur and not self._sw_up_last and (now - self._sw_up_time) > _SW_DEBOUNCE:
            self._sw_up_time = now
            if self.on_adjust:
                self.on_adjust(1)
        self._sw_up_last = cur

        # Switch A — Down
        cur = self._read("pin_sw_down")
        if cur and not self._sw_down_last and (now - self._sw_down_time) > _SW_DEBOUNCE:
            self._sw_down_time = now
            if self.on_adjust:
                self.on_adjust(-1)
        self._sw_down_last = cur

        # Switch B — Select (fire on any change)
        cur = self._read("pin_sw_sel")
        if cur != self._sw_sel_last and (now - self._sw_sel_time) > _SW_DEBOUNCE:
            self._sw_sel_time = now
            if self.on_cycle:
                self.on_cycle()
        self._sw_sel_last = cur

    # -- speaker (software PWM) -------------------------------------------

    def speaker_on(self, freq, volume):
        """Start or update the PWM sidetone.

        *volume* 0-100 maps to duty cycle 0-50%.
        """
        if not HAS_GPIO:
            return
        pin = self._pins["pin_spk"]
        duty = max(0.1, volume * 0.5)

        if self._pwm is not None and self._pwm_pin == pin:
            try:
                self._pwm.ChangeFrequency(max(1, freq))
                self._pwm.ChangeDutyCycle(duty)
                return
            except Exception:
                self._pwm = None

        self.speaker_off()
        try:
            self._pwm = IO.PWM(pin, max(1, freq))
            self._pwm.start(duty)
            self._pwm_pin = pin
        except Exception:
            self._pwm = None

    def speaker_off(self):
        if self._pwm is not None:
            try:
                self._pwm.stop()
            except Exception:
                pass
            self._pwm = None
            self._pwm_pin = -1

    # -- PTT output -------------------------------------------------------

    def set_ptt(self, active):
        if HAS_GPIO:
            IO.output(self._pins["pin_ptt"],
                      IO.HIGH if active else IO.LOW)

    # -- switch callbacks -------------------------------------------------

    def _fire_adjust(self, direction):
        if self.on_adjust:
            self.on_adjust(direction)

    def _fire_cycle(self):
        if self.on_cycle:
            self.on_cycle()
