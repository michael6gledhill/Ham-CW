"""Audio generation and playback for CW tones.

Uses numpy for sine-wave generation and pyaudio (fallback: alsaaudio)
for low-latency audio output.  Runs in a background thread.

Buffer size of 512 samples at 44100 Hz gives ~12 ms latency.
A 5 ms raised-cosine envelope ramp eliminates key-click artefacts.
"""

import array
import math
import threading

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    pyaudio = None
    HAS_PYAUDIO = False

try:
    import alsaaudio
    HAS_ALSA = True
except ImportError:
    alsaaudio = None
    HAS_ALSA = False

SAMPLE_RATE  = 44100
CHANNELS     = 1
BUFFER_SIZE  = 512          # ~12 ms at 44100 Hz
RAMP_MS      = 5
RAMP_SAMPLES = int(SAMPLE_RATE * RAMP_MS / 1000)
TWO_PI       = 2.0 * math.pi


def _find_alsa_device():
    """Try to find a usable ALSA playback device."""
    if not HAS_ALSA:
        return None
    for name in ('plughw:Headphones', 'plughw:2,0', 'plughw:1,0',
                 'plughw:0,0', 'default'):
        try:
            pcm = alsaaudio.PCM(
                type=alsaaudio.PCM_PLAYBACK,
                device=name,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=BUFFER_SIZE,
            )
            pcm.close()
            return name
        except alsaaudio.ALSAAudioError:
            continue
    return None


class AudioEngine:
    """Threaded audio output for CW tone generation."""

    def __init__(self):
        self._freq = 800
        self._key_on = False
        self._phase = 0.0
        self._envelope = 0.0
        self._ramp_inc = 1.0 / max(RAMP_SAMPLES, 1)
        self._running = False
        self._thread = None
        self._backend = None      # 'pyaudio' or 'alsa'
        self._pa = None
        self._stream = None
        self._pcm = None

    # -- public API -------------------------------------------------------

    def start(self):
        """Open audio device and start playback thread."""
        # Try pyaudio first
        if HAS_PYAUDIO:
            try:
                self._pa = pyaudio.PyAudio()
                self._stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    output=True,
                    frames_per_buffer=BUFFER_SIZE,
                )
                self._backend = 'pyaudio'
                print("morse-keyer: audio via pyaudio")
            except Exception as e:
                print(f"morse-keyer: pyaudio failed: {e}")
                self._pa = None
                self._stream = None

        # Fall back to ALSA
        if self._backend is None and HAS_ALSA:
            device = _find_alsa_device()
            if device:
                try:
                    self._pcm = alsaaudio.PCM(
                        type=alsaaudio.PCM_PLAYBACK,
                        device=device,
                        channels=CHANNELS,
                        rate=SAMPLE_RATE,
                        format=alsaaudio.PCM_FORMAT_S16_LE,
                        periodsize=BUFFER_SIZE,
                    )
                    self._backend = 'alsa'
                    print(f"morse-keyer: audio via ALSA ({device})")
                except Exception as e:
                    print(f"morse-keyer: ALSA failed: {e}")

        if self._backend is None:
            print("morse-keyer: no audio backend -- speaker GPIO only")
            return

        self._running = True
        self._thread = threading.Thread(target=self._audio_loop,
                                        daemon=True, name='audio-engine')
        self._thread.start()

    def stop(self):
        """Stop playback thread and release device."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
        if self._pcm:
            try:
                self._pcm.close()
            except Exception:
                pass

    def set_frequency(self, freq):
        self._freq = max(400, min(1000, int(freq)))

    def key_on(self):
        self._key_on = True

    def key_off(self):
        self._key_on = False

    # -- audio thread -----------------------------------------------------

    def _audio_loop(self):
        silence = bytes(BUFFER_SIZE * 2)   # 16-bit = 2 bytes per sample
        ramp_inc = self._ramp_inc
        _sin = math.sin
        _cos = math.cos
        _pi = math.pi

        while self._running:
            # Fast path: total silence
            if not self._key_on and self._envelope <= 0.0:
                self._write(silence)
                continue

            freq = self._freq
            phase_inc = TWO_PI * freq / SAMPLE_RATE

            if HAS_NUMPY:
                buf = self._gen_numpy(ramp_inc, phase_inc, _pi)
            else:
                buf = self._gen_pure(ramp_inc, phase_inc, _sin, _cos, _pi)

            self._write(buf)

    def _gen_numpy(self, ramp_inc, phase_inc, pi):
        """Generate buffer using numpy for the sine computation."""
        samples = np.empty(BUFFER_SIZE, dtype=np.float64)
        phase = self._phase

        # Build envelope array (per-sample for correct ramping)
        env_raw = np.empty(BUFFER_SIZE, dtype=np.float64)
        e = self._envelope
        for i in range(BUFFER_SIZE):
            if self._key_on:
                e = min(1.0, e + ramp_inc)
            else:
                e = max(0.0, e - ramp_inc)
            env_raw[i] = e
        self._envelope = e

        # Raised-cosine shaping
        shaped = 0.5 - 0.5 * np.cos(pi * env_raw)

        # Phase-continuous sine
        phases = phase + np.arange(BUFFER_SIZE) * phase_inc
        self._phase = phases[-1] % TWO_PI
        sine = np.sin(phases)

        out = (32767.0 * shaped * sine).astype(np.int16)
        return out.tobytes()

    def _gen_pure(self, ramp_inc, phase_inc, _sin, _cos, _pi):
        """Generate buffer using pure Python math."""
        buf = array.array('h')
        for _ in range(BUFFER_SIZE):
            if self._key_on:
                self._envelope = min(1.0, self._envelope + ramp_inc)
            else:
                self._envelope = max(0.0, self._envelope - ramp_inc)

            if self._envelope > 0.0:
                env = 0.5 - 0.5 * _cos(_pi * self._envelope)
                sample = int(32767.0 * env * _sin(self._phase))
                self._phase += phase_inc
                if self._phase >= TWO_PI:
                    self._phase -= TWO_PI
            else:
                sample = 0
                self._phase = 0.0
            buf.append(sample)
        return buf.tobytes()

    def _write(self, data):
        try:
            if self._backend == 'pyaudio' and self._stream:
                self._stream.write(data)
            elif self._backend == 'alsa' and self._pcm:
                self._pcm.write(data)
        except Exception:
            pass
