"""GPIO handler for ham-cw keyer.

Manages paddle/switch inputs with interrupt-driven edge detection,
software-PWM sidetone speaker, and PTT output.  Falls back to stubs
when RPi.GPIO is unavailable (desktop testing).
"""

try:
    import RPi.GPIO as IO
    HAS_GPIO = True
except ImportError:
    IO = None
    HAS_GPIO = False

# Debounce times (ms)
_PADDLE_BOUNCE = 5       # paddles need fast response
_SWITCH_BOUNCE = 200     # toggle switches need heavy debounce


class GpioHandler:
    """Set up and interact with all GPIO pins."""

    def __init__(self):
        self._pwm = None
        self._pwm_pin = -1
        self._pins = {}
        self.on_adjust = None      # callback(direction: +1/-1)
        self.on_cycle = None       # callback()

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

        # Edge detection for parameter switches
        IO.add_event_detect(
            self._pins["pin_sw_up"], IO.FALLING,
            callback=lambda _ch: self._fire_adjust(1),
            bouncetime=_SWITCH_BOUNCE)
        IO.add_event_detect(
            self._pins["pin_sw_down"], IO.FALLING,
            callback=lambda _ch: self._fire_adjust(-1),
            bouncetime=_SWITCH_BOUNCE)
        # Switch B: any flip (both edges) cycles the selected parameter
        IO.add_event_detect(
            self._pins["pin_sw_sel"], IO.BOTH,
            callback=lambda _ch: self._fire_cycle(),
            bouncetime=_SWITCH_BOUNCE)

    def cleanup(self):
        """Release GPIO resources."""
        self.speaker_off()
        if HAS_GPIO:
            try:
                IO.cleanup()
            except Exception:
                pass

    # -- paddle reads (called every keyer tick) ---------------------------

    def read_dit(self):
        if not HAS_GPIO:
            return False
        return IO.input(self._pins["pin_dit"]) == 0

    def read_dah(self):
        if not HAS_GPIO:
            return False
        return IO.input(self._pins["pin_dah"]) == 0

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
