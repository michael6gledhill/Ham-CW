"""GPIO handler using pigpio (DMA-timed PWM) for Pi 4.

Features:
    - Interrupt-driven switch handling via pigpio callbacks
    - Hardware debouncing via glitch filter (50 ms)
    - Wired-OR PTT: INPUT hi-Z  or  OUTPUT LOW  -- NEVER HIGH
    - DMA-timed PWM for clean speaker audio

Requires the pigpio daemon:  sudo systemctl enable pigpiod
"""

try:
    import pigpio
    _pi = pigpio.pi()
    HAS_GPIO = _pi.connected
except Exception:
    pigpio = None
    _pi = None
    HAS_GPIO = False

_GLITCH_US = 50_000      # 50 ms glitch filter for switch debounce


class GpioHandler:
    """Set up and interact with all GPIO pins via pigpio."""

    def __init__(self):
        self._pins = {}
        self._tone_on = False
        self._callbacks = []
        self.on_param_cycle = None      # () -> None
        self.on_param_adjust = None     # (direction: int) -> None

    def setup(self, cfg):
        """Configure all GPIO pins from *cfg* dict."""
        self.speaker_off()
        self._cancel_callbacks()
        self._pins = {k: v for k, v in cfg.items() if k.startswith('pin_')}

        if not HAS_GPIO:
            return

        # -- Paddle inputs (pull-up, active low) -------------------------
        for key in ('pin_dit', 'pin_dah'):
            _pi.set_mode(self._pins[key], pigpio.INPUT)
            _pi.set_pull_up_down(self._pins[key], pigpio.PUD_UP)

        # -- Mode switch (pull-up; LOW = text mode) -----------------------
        _pi.set_mode(self._pins['pin_mode'], pigpio.INPUT)
        _pi.set_pull_up_down(self._pins['pin_mode'], pigpio.PUD_UP)

        # -- Parameter-select switch (cycles on any edge) -----------------
        pin_sel = self._pins['pin_sel']
        _pi.set_mode(pin_sel, pigpio.INPUT)
        _pi.set_pull_up_down(pin_sel, pigpio.PUD_UP)
        _pi.set_glitch_filter(pin_sel, _GLITCH_US)
        self._callbacks.append(
            _pi.callback(pin_sel, pigpio.EITHER_EDGE, self._on_sel))

        # -- Adjust up / down (falling-edge trigger) ----------------------
        for key, direction in (('pin_adj_up', 1), ('pin_adj_down', -1)):
            pin = self._pins[key]
            _pi.set_mode(pin, pigpio.INPUT)
            _pi.set_pull_up_down(pin, pigpio.PUD_UP)
            _pi.set_glitch_filter(pin, _GLITCH_US)
            self._callbacks.append(
                _pi.callback(pin, pigpio.FALLING_EDGE,
                             lambda g, l, t, d=direction: self._on_adj(d)))

        # -- Speaker output -----------------------------------------------
        _pi.set_mode(self._pins['pin_spk'], pigpio.OUTPUT)
        _pi.write(self._pins['pin_spk'], 0)

        # -- Speaker ground (tie low) ------------------------------------
        _pi.set_mode(self._pins['pin_spk_gnd'], pigpio.OUTPUT)
        _pi.write(self._pins['pin_spk_gnd'], 0)

        # -- PTT: start in hi-Z ------------------------------------------
        self.set_ptt(False)

    def cleanup(self):
        """Release GPIO resources."""
        self.speaker_off()
        self.set_ptt(False)
        self._cancel_callbacks()

    def _cancel_callbacks(self):
        for cb in self._callbacks:
            try:
                cb.cancel()
            except Exception:
                pass
        self._callbacks.clear()

    # -- Switch callbacks -------------------------------------------------

    def _on_sel(self, gpio, level, tick):
        if self.on_param_cycle:
            self.on_param_cycle()

    def _on_adj(self, direction):
        if self.on_param_adjust:
            self.on_param_adjust(direction)

    # -- Input reads ------------------------------------------------------

    def _read(self, key):
        if not HAS_GPIO:
            return False
        try:
            return _pi.read(self._pins[key]) == 0   # active low
        except Exception:
            return False

    def read_dit(self):
        return self._read('pin_dit')

    def read_dah(self):
        return self._read('pin_dah')

    def read_mode(self):
        """Return 'text' if mode switch is grounded, else 'tx'."""
        return 'text' if self._read('pin_mode') else 'tx'

    # -- PTT (wired-OR: hi-Z  or  OUTPUT LOW  --  NEVER HIGH) ------------

    def set_ptt(self, active):
        """Ground PTT line (active=True) or release to hi-Z.

        SAFETY: GPIO_PTT must NEVER drive HIGH.
        Two states only:
            INPUT + PUD_OFF   -> high impedance (idle)
            OUTPUT LOW        -> pull PTT line to ground (transmit)
        """
        if not HAS_GPIO:
            return
        pin = self._pins.get('pin_ptt')
        if pin is None:
            return
        try:
            if active:
                _pi.set_mode(pin, pigpio.OUTPUT)
                _pi.write(pin, 0)
            else:
                _pi.set_mode(pin, pigpio.INPUT)
                _pi.set_pull_up_down(pin, pigpio.PUD_OFF)
        except Exception:
            pass

    # -- Speaker (DMA-timed PWM via pigpio) -------------------------------

    def speaker_on(self, freq):
        """Start or update tone at *freq* Hz."""
        if not HAS_GPIO:
            return
        pin = self._pins['pin_spk']
        freq = max(1, min(40000, int(freq)))
        try:
            _pi.set_PWM_frequency(pin, freq)
            _pi.set_PWM_dutycycle(pin, 128)      # 50 % duty
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

    # -- Pin scanning (detect feature) ------------------------------------

    def scan_pins(self):
        """Return list of GPIO pins currently pulled LOW."""
        if not HAS_GPIO:
            return []

        from config import OUTPUT_PINS
        skip = set()
        for key in OUTPUT_PINS:
            if key in self._pins:
                skip.add(self._pins[key])
        ptt = self._pins.get('pin_ptt')
        if ptt is not None:
            skip.add(ptt)

        active = []
        for pin in range(2, 28):
            if pin in skip:
                continue
            try:
                _pi.set_mode(pin, pigpio.INPUT)
                _pi.set_pull_up_down(pin, pigpio.PUD_UP)
                if _pi.read(pin) == 0:
                    active.append(pin)
            except Exception:
                continue
        return active
