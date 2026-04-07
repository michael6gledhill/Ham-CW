"""ALSA audio engine for ham-cw keyer.

Generates a clean sine-wave tone on the Pi 4's built-in 3.5mm TRRS
jack.  Left channel carries the tone to the Baofeng mic input; right
channel is silent.

Uses a pre-computed one-second ring buffer at full scale.  Volume is
applied at output time so changes are instant without rebuilding the
ring.  A 5 ms raised-cosine envelope ramp eliminates key clicks.
"""

import array as _array
import math
import threading

try:
    import alsaaudio
    _HAS_ALSA = True
except ImportError:
    alsaaudio = None
    _HAS_ALSA = False

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------
SAMPLE_RATE = 48000
PERIOD_SIZE = 512          # ~10.7 ms per block — low latency, fine on Pi 4
CHANNELS = 2               # stereo (L = tone, R = silent)
RAMP_MS = 5                # envelope ramp duration
_WAVE_LEN = 4096           # sine look-up table length

# Pre-computed full-scale sine table  (-32767 .. +32767)
_WAVETABLE = _array.array('h',
    (int(32767 * math.sin(2 * math.pi * i / _WAVE_LEN))
     for i in range(_WAVE_LEN)))


# ---------------------------------------------------------------------------
#  Audio engine
# ---------------------------------------------------------------------------
class AudioEngine:
    """Background thread that outputs PCM audio to ALSA."""

    def __init__(self):
        self.key_down = False          # set by main keyer loop
        self._freq = 700
        self._volume = 0.7             # 0.0 .. 1.0
        self._lock = threading.Lock()
        self._shutdown = threading.Event()

        # Ring buffer (rebuilt when freq changes)
        self._ring = None
        self._ring_freq = -1

        self._thread = None

    # -- public API -------------------------------------------------------

    def start(self):
        if not _HAS_ALSA:
            print("ham-cw: alsaaudio not available — ALSA output disabled")
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="audio-engine")
        self._thread.start()

    def stop(self):
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=2)

    def set_key(self, down):
        self.key_down = down

    def update(self, freq=None, volume=None):
        with self._lock:
            if freq is not None:
                self._freq = max(200, min(2000, freq))
            if volume is not None:
                self._volume = max(0, min(100, volume)) / 100.0

    # -- internals --------------------------------------------------------

    def _rebuild_ring(self, freq):
        """Pre-compute one second of full-scale sine at *freq* Hz."""
        sr = SAMPLE_RATE
        wt = _WAVETABLE
        wl = _WAVE_LEN
        pinc = freq * wl / sr
        self._ring = _array.array('h',
            (wt[int(i * pinc) % wl] for i in range(sr)))
        self._ring_freq = freq

    def _run(self):                             # noqa: C901  (audio loop)
        # Open ALSA PCM device
        try:
            pcm = alsaaudio.PCM(
                type=alsaaudio.PCM_PLAYBACK,
                device='default',
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=PERIOD_SIZE,
            )
        except Exception as e:
            print(f"ham-cw: failed to open ALSA device: {e}")
            return

        sr = SAMPLE_RATE
        period = PERIOD_SIZE
        ramp_step = 1.0 / (sr * RAMP_MS / 1000.0)
        envelope = 0.0
        ring_pos = 0
        silence = bytes(period * CHANNELS * 2)   # 16-bit stereo zeros

        while not self._shutdown.is_set():
            with self._lock:
                freq = self._freq
                vol = self._volume

            # Rebuild ring when frequency changes
            if freq != self._ring_freq:
                self._rebuild_ring(freq)
            ring = self._ring

            target = 1.0 if self.key_down else 0.0

            # -- fast path: complete silence ------------------------------
            if envelope == 0.0 and target == 0.0:
                try:
                    pcm.write(silence)
                except Exception:
                    pass
                ring_pos = (ring_pos + period) % sr
                continue

            # -- fast path: steady tone (envelope fully on) ---------------
            if envelope >= 1.0 and target >= 1.0:
                pos = ring_pos
                end = pos + period
                if end <= sr:
                    mono = ring[pos:end]
                else:
                    mono = ring[pos:] + ring[:end - sr]
                ring_pos = end % sr

                # Left channel = tone * volume, right = 0
                st = _array.array('h', [0]) * (period * 2)
                for i in range(period):
                    st[i * 2] = int(mono[i] * vol)
                    # st[i*2+1] stays 0
                try:
                    pcm.write(st.tobytes())
                except Exception:
                    pass
                continue

            # -- envelope transition (5 ms ramp) --------------------------
            st = _array.array('h', [0]) * (period * 2)
            pos = ring_pos
            for i in range(period):
                if envelope < target:
                    envelope = min(envelope + ramp_step, 1.0)
                elif envelope > target:
                    envelope = max(envelope - ramp_step, 0.0)
                st[i * 2] = int(ring[pos] * envelope * vol)
                pos += 1
                if pos >= sr:
                    pos = 0
            ring_pos = pos

            try:
                pcm.write(st.tobytes())
            except Exception:
                pass

        pcm.close()
