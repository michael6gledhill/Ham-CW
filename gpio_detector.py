"""GPIO auto-detection via raw RPi.GPIO polling at 200Hz.

Reads ALL candidate pins (2-27) simultaneously every 5ms using
RPi.GPIO.input() — no callbacks, no event detection, no bounce_time.
Detects state change when current value differs from initial AND has
been stable for 2 consecutive reads (10ms debounce).
"""

import threading
import time
import collections

try:
    import RPi.GPIO as GPIO
    HAS_RPI_GPIO = True
except ImportError:
    GPIO = None
    HAS_RPI_GPIO = False

# How many previous reads to keep per pin
BUFFER_SIZE = 10
# Consecutive stable reads required to confirm a change
STABLE_READS = 2
# Auto-timeout (seconds)
TIMEOUT = 10.0
# Poll interval (seconds) — 200 Hz
POLL_INTERVAL = 0.005


class GPIODetector:
    """Active-polling GPIO pin change detector."""

    def __init__(self):
        self.lock = threading.Lock()
        self.is_detecting = False
        self.detected_pins = []      # pins that changed (most recent first)
        self.pin_buffers = {}        # {pin: deque of last N reads}
        self.initial_state = {}      # {pin: value at start}
        self.confirmed = {}          # {pin: True} pins already confirmed
        self._thread = None
        self._start_time = 0
        self._timed_out = False
        self._error = None
        self._role = None            # which role we're detecting for
        self._exclude_pins = set()   # pins to skip (assigned to other roles)

    def start(self, role=None, exclude_pins=None):
        """Begin active polling on all candidate GPIO pins."""
        if not HAS_RPI_GPIO:
            with self.lock:
                self._error = 'RPi.GPIO not available'
            return False

        self.stop()  # clean up any previous run

        with self.lock:
            self.is_detecting = True
            self.detected_pins = []
            self.pin_buffers = {}
            self.initial_state = {}
            self.confirmed = {}
            self._timed_out = False
            self._error = None
            self._role = role
            self._exclude_pins = set(exclude_pins or [])
            self._start_time = time.monotonic()

        self._thread = threading.Thread(target=self._poll_loop,
                                        daemon=True, name='gpio-detector')
        self._thread.start()
        return True

    def stop(self):
        """Stop the polling loop and clean up GPIO."""
        with self.lock:
            self.is_detecting = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def get_status(self):
        """Return current detection status (thread-safe snapshot)."""
        with self.lock:
            return {
                'detecting':     self.is_detecting,
                'detected_pins': list(self.detected_pins),
                'timed_out':     self._timed_out,
                'error':         self._error,
                'role':          self._role,
                'elapsed':       round(time.monotonic() - self._start_time, 1)
                                 if self.is_detecting else 0,
            }

    def _poll_loop(self):
        """200Hz polling loop reading all candidate pins simultaneously."""
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
        except Exception as e:
            with self.lock:
                self._error = f'GPIO init failed: {e}'
                self.is_detecting = False
            return

        # Set up all candidate pins as inputs with pull-up
        candidates = []
        for pin in range(2, 28):
            if pin in self._exclude_pins:
                continue
            try:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                candidates.append(pin)
            except Exception:
                continue

        # Let pull-ups settle
        time.sleep(0.05)

        # Record initial state
        with self.lock:
            for pin in candidates:
                try:
                    val = GPIO.input(pin)
                    self.initial_state[pin] = val
                    self.pin_buffers[pin] = collections.deque(
                        [val] * BUFFER_SIZE, maxlen=BUFFER_SIZE)
                except Exception:
                    pass

        print(f"morse-keyer: detector polling {len(candidates)} pins"
              f" for {self._role}")

        # Main poll loop at 200Hz
        while True:
            with self.lock:
                if not self.is_detecting:
                    break

            # Check timeout
            elapsed = time.monotonic() - self._start_time
            if elapsed >= TIMEOUT:
                with self.lock:
                    self._timed_out = True
                    self.is_detecting = False
                print("morse-keyer: detection timed out")
                break

            # Read ALL pins
            for pin in candidates:
                try:
                    val = GPIO.input(pin)
                except Exception:
                    continue

                with self.lock:
                    buf = self.pin_buffers.get(pin)
                    if buf is None:
                        continue
                    buf.append(val)
                    init = self.initial_state.get(pin)

                    # Skip if already confirmed
                    if pin in self.confirmed:
                        continue

                    # Check: value differs from initial AND stable for
                    # STABLE_READS consecutive reads
                    if val != init:
                        stable = True
                        for i in range(1, STABLE_READS + 1):
                            if len(buf) >= i and buf[-i] != val:
                                stable = False
                                break
                        if stable:
                            self.confirmed[pin] = True
                            self.detected_pins.insert(0, pin)
                            print(f"morse-keyer: detected GPIO {pin}"
                                  f" (was {init}, now {val})")

            time.sleep(POLL_INTERVAL)

        # Clean up — release pins we set up
        try:
            for pin in candidates:
                try:
                    GPIO.cleanup(pin)
                except Exception:
                    pass
        except Exception:
            pass
