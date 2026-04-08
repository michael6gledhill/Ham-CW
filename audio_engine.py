"""ALSA audio engine for CW tone output.

Generates a sine wave on the left channel (right channel silent)
for driving a UV-5R radio via TRRS 3.5 mm jack.

Features:
    - Phase-continuous sine wave
    - 8 ms raised-cosine envelope for click-free keying
    - Volume scaling (0-100)
    - Auto-detection of Pi 4 headphone jack
"""

import array
import math
import threading

try:
    import alsaaudio
    HAS_ALSA = True
except ImportError:
    alsaaudio = None
    HAS_ALSA = False

SAMPLE_RATE  = 48000
CHANNELS     = 2           # stereo: left = tone, right = silent
PERIOD_SIZE  = 480         # 10 ms at 48 kHz
RAMP_MS      = 8
RAMP_SAMPLES = int(SAMPLE_RATE * RAMP_MS / 1000)   # 384
TWO_PI       = 2.0 * math.pi


def _find_device():
    """Auto-detect the Pi 4 headphone jack ALSA device."""
    if not HAS_ALSA:
        return None
    for name in ('plughw:Headphones', 'plughw:2,0', 'plughw:1,0', 'default'):
        try:
            pcm = alsaaudio.PCM(
                type=alsaaudio.PCM_PLAYBACK,
                device=name,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=PERIOD_SIZE,
            )
            pcm.close()
            return name
        except alsaaudio.ALSAAudioError:
            continue
    return None


class AudioEngine:
    """Threaded ALSA audio output for CW tone."""

    def __init__(self):
        self._freq = 700
        self._volume = 70           # 0-100
        self._key_on = False
        self._phase = 0.0
        self._envelope = 0.0        # 0.0 .. 1.0 linear, shaped by cosine
        self._ramp_inc = 1.0 / max(RAMP_SAMPLES, 1)
        self._running = False
        self._thread = None
        self._pcm = None
        self._device = None

    # -- public API -------------------------------------------------------

    def start(self):
        """Open ALSA device and start audio thread."""
        if not HAS_ALSA:
            print("ham-cw: alsaaudio not available -- no ALSA output")
            return
        self._device = _find_device()
        if self._device is None:
            print("ham-cw: no ALSA playback device found")
            return
        try:
            self._pcm = alsaaudio.PCM(
                type=alsaaudio.PCM_PLAYBACK,
                device=self._device,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=PERIOD_SIZE,
            )
        except alsaaudio.ALSAAudioError as e:
            print(f"ham-cw: ALSA open failed: {e}")
            return

        self._running = True
        self._thread = threading.Thread(target=self._audio_loop,
                                        daemon=True, name='audio-engine')
        self._thread.start()
        print(f"ham-cw: ALSA output on {self._device}")

    def stop(self):
        """Stop audio thread and close ALSA device."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._pcm:
            try:
                self._pcm.close()
            except Exception:
                pass
            self._pcm = None

    def set_key(self, on):
        """Set key state (True = tone on)."""
        self._key_on = on

    def set_freq(self, freq):
        self._freq = freq

    def set_volume(self, volume):
        self._volume = max(0, min(100, volume))

    # -- audio thread -----------------------------------------------------

    def _audio_loop(self):
        """Continuously generate audio buffers.

        When key is off and envelope is fully decayed, a pre-computed
        silence buffer is written to keep the ALSA stream alive without
        per-sample math overhead.
        """
        silence = bytes(PERIOD_SIZE * CHANNELS * 2)
        ramp_inc = self._ramp_inc
        _sin = math.sin
        _cos = math.cos
        _pi = math.pi

        while self._running:
            # Fast path -- complete silence
            if not self._key_on and self._envelope <= 0.0:
                try:
                    self._pcm.write(silence)
                except Exception:
                    pass
                continue

            buf = array.array('h')
            freq = self._freq
            vol = self._volume / 100.0
            phase_inc = TWO_PI * freq / SAMPLE_RATE

            for _ in range(PERIOD_SIZE):
                # Envelope ramp
                if self._key_on:
                    if self._envelope < 1.0:
                        self._envelope = min(1.0, self._envelope + ramp_inc)
                else:
                    if self._envelope > 0.0:
                        self._envelope = max(0.0, self._envelope - ramp_inc)

                if self._envelope > 0.0:
                    # Raised-cosine shaping: smooth S-curve 0->1
                    env = 0.5 - 0.5 * _cos(_pi * self._envelope)
                    sample = int(32767.0 * vol * env * _sin(self._phase))
                    self._phase += phase_inc
                    if self._phase >= TWO_PI:
                        self._phase -= TWO_PI
                else:
                    sample = 0
                    self._phase = 0.0

                buf.append(sample)      # left channel  (tone)
                buf.append(0)           # right channel (silent)

            try:
                self._pcm.write(buf.tobytes())
            except Exception:
                pass
