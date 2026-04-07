#!/usr/bin/env python3
"""ham-cw  --  Python CW iambic keyer for Raspberry Pi

Hardware:
  Paddles: common-ground, wires to GPIO (active-low with internal pull-up)
  ReSpeaker 2-Mic HAT for audio (speaker + headphone)

Default wiring (BCM numbers, avoid ReSpeaker HAT pins 2,3,17,18-21):
  GPIO  5  <- DIT paddle   (pulled HIGH, grounded when pressed)
  GPIO  6  <- DAH paddle   (pulled HIGH, grounded when pressed)
  GPIO 13  <- TX switch     (pulled HIGH, grounded = TX mode)
  GPIO 16  <- RX switch     (pulled HIGH, grounded = RX mode)

Usage:  python3 ham_cw.py [WPM]
Web UI: http://<pi-ip>:8080
"""

import json
import math
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ---------------------------------------------------------------------------
#  Optional hardware imports (graceful degradation on dev machines)
# ---------------------------------------------------------------------------
try:
    import RPi.GPIO as IO
    IO.setmode(IO.BCM)
    IO.setwarnings(False)
    HAS_GPIO = True
except (ImportError, RuntimeError):
    HAS_GPIO = False
    print("ham-cw: RPi.GPIO not available - GPIO disabled")

try:
    import alsaaudio
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False
    print("ham-cw: alsaaudio not available - sidetone disabled")

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------
CONFIG_PATH = Path.home() / ".ham-cw.conf"
SAMPLE_RATE = 48000
HTTP_PORT = 8080

DEFAULTS = {
    "wpm": 20,
    "freq": 700,
    "weight": 300,
    "volume": 70,
    "pin_dit": 5,
    "pin_dah": 6,
    "pin_tx": 13,
    "pin_rx": 16,
}

# ---------------------------------------------------------------------------
#  Shared state  (GIL makes simple bool/int read-write safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_config = dict(DEFAULTS)
_shutdown = threading.Event()

key_flag = False          # True while sidetone should sound
dit_live = False          # live paddle state for web monitor
dah_live = False
tx_live = False
rx_live = False
test_requested = False    # set by HTTP, cleared by main loop

# Text send queue (protected by its own lock)
_send_lock = threading.Lock()
_send_queue = []

# ---------------------------------------------------------------------------
#  Config persistence
# ---------------------------------------------------------------------------
def _clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


def load_config():
    global _config
    try:
        data = json.loads(CONFIG_PATH.read_text())
        with _lock:
            for k in DEFAULTS:
                if k in data:
                    _config[k] = data[k]
        print(f"ham-cw: loaded config from {CONFIG_PATH}")
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        print(f"ham-cw: using defaults ({e})")


def save_config():
    with _lock:
        data = dict(_config)
    try:
        CONFIG_PATH.write_text(json.dumps(data, indent=2))
    except OSError as e:
        print(f"ham-cw: save error: {e}")


def get_config():
    with _lock:
        return dict(_config)


def apply_config(body):
    """Parse JSON, merge into config with clamping, save, return result."""
    try:
        vals = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return get_config()
    with _lock:
        if "wpm"    in vals: _config["wpm"]    = _clamp(vals["wpm"], 5, 60)
        if "freq"   in vals: _config["freq"]   = _clamp(vals["freq"], 200, 2000)
        if "weight" in vals: _config["weight"] = _clamp(vals["weight"], 200, 500)
        if "volume" in vals: _config["volume"] = _clamp(vals["volume"], 0, 100)
        if "pin_dit" in vals: _config["pin_dit"] = _clamp(vals["pin_dit"], 0, 27)
        if "pin_dah" in vals: _config["pin_dah"] = _clamp(vals["pin_dah"], 0, 27)
        if "pin_tx"  in vals: _config["pin_tx"]  = _clamp(vals["pin_tx"], 0, 27)
        if "pin_rx"  in vals: _config["pin_rx"]  = _clamp(vals["pin_rx"], 0, 27)
        result = dict(_config)
    save_config()
    set_system_volume(result["volume"])
    return result

# ---------------------------------------------------------------------------
#  Volume (ReSpeaker 2-Mic HAT / WM8960)
# ---------------------------------------------------------------------------
def set_system_volume(vol):
    pct = f"{_clamp(vol, 0, 100)}%"
    for ctrl in ["Playback", "Speaker Playback Volume",
                 "Headphone Playback Volume"]:
        subprocess.Popen(
            ["amixer", "-c", "seeed2micvoicec", "sset", ctrl, pct],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

# ---------------------------------------------------------------------------
#  IP announcement  (hold both paddles 3 s)
# ---------------------------------------------------------------------------
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def announce_ip():
    ip = get_ip()
    if ip:
        readable = " dot ".join(" ".join(d for d in octet)
                                for octet in ip.split("."))
        text = f"My IP address is {readable}"
    else:
        text = "No network connection"
    wav = os.path.join(tempfile.gettempdir(), "ham_cw_ip.wav")
    subprocess.run(["espeak", "-s", "130", "-w", wav, text],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["aplay", wav],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.remove(wav)
    except OSError:
        pass

# ---------------------------------------------------------------------------
#  Iambic Mode-B keyer
# ---------------------------------------------------------------------------
DIT, DAH = 0, 1
IDLE, SENDING, SPACING = 0, 1, 2


class Keyer:
    def __init__(self, wpm):
        self.phase = IDLE
        self.element = None
        self.last = None
        self.dit_mem = False
        self.dah_mem = False
        self.timer = time.monotonic()
        self.unit = 1.2 / max(5, wpm)   # dit duration in seconds

    def set_wpm(self, wpm):
        self.unit = 1.2 / max(5, min(60, wpm))

    def tick(self, dit_dn, dah_dn, weight):
        """Call every ~1 ms.  Returns True while tone should sound."""
        if dit_dn:
            self.dit_mem = True
        if dah_dn:
            self.dah_mem = True
        now = time.monotonic()

        if self.phase == IDLE:
            el = self._choose(dit_dn, dah_dn)
            if el is not None:
                self._begin(el, now)
                return True
            return False

        if self.phase == SENDING:
            dur = self.unit if self.element == DIT else self.unit * weight / 100
            if now - self.timer >= dur:
                if dit_dn:
                    self.dit_mem = True
                if dah_dn:
                    self.dah_mem = True
                self.last = self.element
                self.phase = SPACING
                self.timer = now
                return False
            return True

        if self.phase == SPACING:
            if now - self.timer >= self.unit:
                el = self._choose(dit_dn, dah_dn)
                if el is not None:
                    self._begin(el, now)
                    return True
                self.phase = IDLE
                self.last = None
            return False

        return False

    # -- internals --
    def _choose(self, dit_dn, dah_dn):
        want_dit = self.dit_mem or dit_dn
        want_dah = self.dah_mem or dah_dn
        if want_dit:
            self.dit_mem = False
        if want_dah:
            self.dah_mem = False
        if not want_dit and not want_dah:
            return None
        if want_dit and not want_dah:
            return DIT
        if want_dah and not want_dit:
            return DAH
        # squeeze: alternate
        if self.last is None or self.last == DAH:
            return DIT
        return DAH

    def _begin(self, el, now):
        self.element = el
        self.phase = SENDING
        self.timer = now

# ---------------------------------------------------------------------------
#  Morse table + send_text
# ---------------------------------------------------------------------------
MORSE = {
    'A': '.-',    'B': '-...',  'C': '-.-.',  'D': '-..',   'E': '.',
    'F': '..-.',  'G': '--.',   'H': '....',  'I': '..',    'J': '.---',
    'K': '-.-',   'L': '.-..',  'M': '--',    'N': '-.',    'O': '---',
    'P': '.--.',  'Q': '--.-',  'R': '.-.',   'S': '...',   'T': '-',
    'U': '..-',   'V': '...-',  'W': '.--',   'X': '-..-',  'Y': '-.--',
    'Z': '--..',
    '0': '-----', '1': '.----', '2': '..---', '3': '...--', '4': '....-',
    '5': '.....', '6': '-....', '7': '--...', '8': '---..', '9': '----.',
    '.': '.-.-.-', ',': '--..--', '?': '..--..', '/': '-..-.',
}


def send_text(text):
    global key_flag
    cfg = get_config()
    unit = 1.2 / cfg["wpm"]
    dah = unit * cfg["weight"] / 100
    for ch in text.upper():
        if ch == ' ':
            time.sleep(unit * 7)
            continue
        morse = MORSE.get(ch)
        if not morse:
            continue
        for i, sym in enumerate(morse):
            key_flag = True
            time.sleep(dah if sym == '-' else unit)
            key_flag = False
            if i + 1 < len(morse):
                time.sleep(unit)
        time.sleep(unit * 3)

# ---------------------------------------------------------------------------
#  Sidetone audio thread
# ---------------------------------------------------------------------------
import array as _array

# Pre-computed wavetable — 2048 entries of one full sine cycle
_WAVE_LEN = 2048
_WAVETABLE = [int(math.sin(2.0 * math.pi * i / _WAVE_LEN) * 32767)
              for i in range(_WAVE_LEN)]

# Larger period = fewer wakeups = Pi Zero can keep up
_TONE_PERIOD = 1024


def sidetone_thread():
    if not HAS_AUDIO:
        return

    # Try devices in order: default (dmix), then direct hardware
    devices = ["default", "plughw:seeed2micvoicec", "plughw:1,0"]
    pcm = None
    for dev in devices:
        try:
            pcm = alsaaudio.PCM(
                type=alsaaudio.PCM_PLAYBACK,
                device=dev,
                channels=1,
                rate=SAMPLE_RATE,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=_TONE_PERIOD,
            )
            print(f"ham-cw: sidetone using ALSA device '{dev}'")
            break
        except Exception:
            pcm = None
            continue
    if pcm is None:
        print("ham-cw: no audio device found - no sidetone")
        return

    # Phase accumulator: fixed-point, 16.16 format stepping through wavetable
    phase_acc = 0
    last_freq = 0
    phase_inc = 0   # how much to advance per sample (fixed-point)

    envelope = 0.0
    RAMP_STEP = 1.0 / (SAMPLE_RATE * 0.005)  # 5 ms ramp

    # Pre-allocate
    wavetable = _WAVETABLE
    wave_len = _WAVE_LEN
    silence = bytes(_TONE_PERIOD * 2)

    while not _shutdown.is_set():
        cfg = get_config()
        freq = cfg["freq"]
        vol = cfg["volume"] / 100.0

        if freq != last_freq:
            # Fixed-point increment: freq * table_len / sample_rate * 65536
            phase_inc = int(freq * wave_len * 65536 / SAMPLE_RATE)
            last_freq = freq

        target = 1.0 if key_flag else 0.0

        # Fast path: fully silent and target is silent
        if envelope == 0.0 and target == 0.0:
            try:
                pcm.write(silence)
            except Exception:
                pass
            continue

        # Build buffer using wavetable lookup — much faster than math.sin()
        samples = _array.array('h', [0]) * _TONE_PERIOD
        env = envelope
        rs = RAMP_STEP
        pa = phase_acc
        wl_mask = wave_len - 1  # power of 2, so mask works

        for i in range(_TONE_PERIOD):
            # Ramp envelope
            if env < target:
                env = min(env + rs, 1.0)
            elif env > target:
                env = max(env - rs, 0.0)

            # Wavetable lookup (top bits of fixed-point accumulator)
            idx = (pa >> 16) & wl_mask
            samples[i] = int(wavetable[idx] * vol * env)
            pa += phase_inc

        # Store state back
        envelope = env
        phase_acc = pa & 0xFFFFFFFF  # keep 32-bit

        try:
            pcm.write(samples.tobytes())
        except Exception:
            pass

    pcm.close()

# ---------------------------------------------------------------------------
#  GPIO helpers
# ---------------------------------------------------------------------------
def setup_pins(cfg):
    if not HAS_GPIO:
        return
    for pin in (cfg["pin_dit"], cfg["pin_dah"], cfg["pin_tx"], cfg["pin_rx"]):
        IO.setup(pin, IO.IN, pull_up_down=IO.PUD_UP)
    print(f"ham-cw: GPIO  DIT={cfg['pin_dit']}  DAH={cfg['pin_dah']}"
          f"  TX={cfg['pin_tx']}  RX={cfg['pin_rx']}")


def read_pin(pin):
    if not HAS_GPIO:
        return False
    return IO.input(pin) == 0   # active-low

# ---------------------------------------------------------------------------
#  HTTP server
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _respond(self, code, body, ctype="text/plain"):
        data = body.encode() if isinstance(body, str) else body
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == "/config":
            self._respond(200, json.dumps(get_config()), "application/json")
        elif self.path == "/paddles":
            self._respond(200, json.dumps({
                "dit": dit_live, "dah": dah_live,
                "tx": tx_live, "rx": rx_live,
                "keyed": key_flag,
            }), "application/json")
        elif self.path == "/":
            self._respond(200, HTML, "text/html; charset=utf-8")
        else:
            self._respond(404, "not found")

    def do_POST(self):
        global test_requested
        length = int(self.headers.get("Content-Length", 0))
        if length > 512:
            self._respond(413, "too large")
            return
        body = self.rfile.read(length).decode() if length > 0 else ""

        if self.path == "/config":
            result = apply_config(body)
            self._respond(200, json.dumps(result), "application/json")
        elif self.path == "/test":
            test_requested = True
            self._respond(200, "ok")
        elif self.path == "/send":
            text = body.strip()
            if not text:
                self._respond(400, "empty")
                return
            with _send_lock:
                if _send_queue:
                    self._respond(503, "busy")
                    return
                _send_queue.append(text)
            self._respond(200, "queued")
        else:
            self._respond(404, "not found")


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def http_thread():
    server = ReusableHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    print(f"ham-cw web UI: http://0.0.0.0:{HTTP_PORT}")
    server.serve_forever()

# ---------------------------------------------------------------------------
#  Main loop
# ---------------------------------------------------------------------------
def main():
    global key_flag, dit_live, dah_live, tx_live, rx_live, test_requested

    wpm_arg = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None

    load_config()
    if wpm_arg:
        with _lock:
            _config["wpm"] = _clamp(wpm_arg, 5, 60)
    cfg = get_config()

    print(f"ham-cw starting - {cfg['wpm']} WPM, {cfg['freq']} Hz, vol {cfg['volume']}%")

    # GPIO
    setup_pins(cfg)
    cur_pins = (cfg["pin_dit"], cfg["pin_dah"], cfg["pin_tx"], cfg["pin_rx"])

    set_system_volume(cfg["volume"])

    # Signals
    def on_sig(sig, frame):
        _shutdown.set()
    signal.signal(signal.SIGINT, on_sig)
    signal.signal(signal.SIGTERM, on_sig)

    # Threads
    threading.Thread(target=sidetone_thread, daemon=True, name="sidetone").start()
    threading.Thread(target=http_thread, daemon=True, name="http").start()

    # Keyer
    keyer = Keyer(cfg["wpm"])
    last_wpm = cfg["wpm"]
    both_since = None

    while not _shutdown.is_set():
        cfg = get_config()

        # Update WPM if changed
        if cfg["wpm"] != last_wpm:
            keyer.set_wpm(cfg["wpm"])
            last_wpm = cfg["wpm"]

        # Hot-reload GPIO pins
        new_pins = (cfg["pin_dit"], cfg["pin_dah"], cfg["pin_tx"], cfg["pin_rx"])
        if new_pins != cur_pins:
            if HAS_GPIO:
                for p in cur_pins:
                    if p not in new_pins:
                        try:
                            IO.cleanup(p)
                        except Exception:
                            pass
            setup_pins(cfg)
            cur_pins = new_pins

        # Test tone from web UI
        if test_requested:
            test_requested = False
            unit = 1.2 / cfg["wpm"]
            dah = unit * cfg["weight"] / 100
            key_flag = True;  time.sleep(unit)
            key_flag = False; time.sleep(unit)
            key_flag = True;  time.sleep(dah)
            key_flag = False
            continue

        # Queued text from web UI
        with _send_lock:
            queued = _send_queue.pop(0) if _send_queue else None
        if queued:
            send_text(queued)
            continue

        # Read paddles (active-low)
        dit_dn = read_pin(cfg["pin_dit"])
        dah_dn = read_pin(cfg["pin_dah"])
        tx_on  = read_pin(cfg["pin_tx"])
        rx_on  = read_pin(cfg["pin_rx"])

        dit_live = dit_dn
        dah_live = dah_dn
        tx_live  = tx_on
        rx_live  = rx_on

        # Both paddles held 3 seconds -> announce IP (works regardless of TX)
        if dit_dn and dah_dn:
            if both_since is None:
                both_since = time.monotonic()
            elif time.monotonic() - both_since >= 3.0:
                key_flag = False
                print("ham-cw: announcing IP address")
                announce_ip()
                both_since = None
                # Wait for release
                while (read_pin(cfg["pin_dit"]) and read_pin(cfg["pin_dah"])
                       and not _shutdown.is_set()):
                    time.sleep(0.01)
                continue
        else:
            both_since = None

        # Iambic keyer — always runs so paddles always produce sidetone.
        # TX/RX switch state is tracked for the web UI and future PTT use.
        key_flag = keyer.tick(dit_dn, dah_dn, cfg["weight"])

        time.sleep(0.001)

    # Shutdown
    print("\nham-cw shutting down")
    key_flag = False
    if HAS_GPIO:
        IO.cleanup()

# ---------------------------------------------------------------------------
#  Embedded HTML
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ham-cw</title>
<style>
  body{font-family:monospace;max-width:420px;margin:2rem auto;background:#111;color:#0f0;padding:1rem}
  h2{margin:1.2rem 0 .4rem;color:#0a0;font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;border-bottom:1px solid #0a0;padding-bottom:.2rem}
  .row{display:flex;align-items:center;gap:.6rem;margin:.4rem 0}
  label{width:8rem;color:#080;flex-shrink:0}
  input[type=range]{flex:1;min-width:0;accent-color:#0a0}
  span.val{width:3.5rem;text-align:right;font-size:.9rem}
  .num{width:3.5rem;background:#000;color:#0f0;border:1px solid #0a0;padding:.3rem .4rem;font:inherit}
  textarea{width:100%;box-sizing:border-box;background:#000;color:#0f0;border:1px solid #0a0;padding:.4rem;font:inherit;resize:vertical}
  button{padding:.35rem 1rem;background:#0a0;color:#000;border:none;font:inherit;cursor:pointer}
  button:active{opacity:.6}
  .m{min-height:1.1em;font-size:.82rem;margin-top:.3rem}
  .led{display:inline-block;padding:.3rem .7rem;border:1px solid #0a0;border-radius:.2rem;font-size:.8rem;color:#040;background:#010;margin-right:.3rem;transition:all .15s}
  .led.on{color:#0f0;background:#040;box-shadow:0 0 6px #0f0}
</style>
</head>
<body>
<h1 style="margin:0 0 .5rem;font-size:1.3rem">ham-cw settings</h1>

<h2>Speed</h2>
<div class="row">
  <label>WPM</label>
  <input id="wpm" type="range" min="5" max="60" value="20"
         oninput="document.getElementById('wpmv').textContent=this.value">
  <span class="val" id="wpmv">20</span>
</div>

<h2>Tone</h2>
<div class="row">
  <label>Frequency (Hz)</label>
  <input id="freq" type="range" min="200" max="2000" step="10" value="700"
         oninput="document.getElementById('freqv').textContent=this.value">
  <span class="val" id="freqv">700</span>
</div>
<div class="row">
  <label>Dash weight</label>
  <input id="weight" type="range" min="200" max="500" step="10" value="300"
         oninput="document.getElementById('weightv').textContent=(this.value/100).toFixed(1)+'x'">
  <span class="val" id="weightv">3.0x</span>
</div>

<h2>Volume</h2>
<div class="row">
  <label>Master volume</label>
  <input id="vol" type="range" min="0" max="100" value="70"
         oninput="document.getElementById('volv').textContent=this.value+'%'">
  <span class="val" id="volv">70%</span>
</div>

<h2>GPIO pins (BCM)</h2>
<div class="row"><label>DIT paddle</label><input id="pin_dit" type="number" min="0" max="27" value="5" class="num"></div>
<div class="row"><label>DAH paddle</label><input id="pin_dah" type="number" min="0" max="27" value="6" class="num"></div>
<div class="row"><label>TX switch</label><input id="pin_tx" type="number" min="0" max="27" value="13" class="num"></div>
<div class="row"><label>RX switch</label><input id="pin_rx" type="number" min="0" max="27" value="16" class="num"></div>
<p style="font-size:.75rem;color:#060;margin:.3rem 0 0">Active-low (grounded when pressed). Avoid GPIO 2,3,17,18-21 (ReSpeaker HAT). Hold both paddles 3 s to announce IP.</p>

<div class="row"><button onclick="saveAll()">Apply settings</button></div>
<div id="sm" class="m"></div>

<h2>Test</h2>
<div class="row">
  <button onclick="testTone()">Test tone (dit-dah)</button>
  <button id="padBtn" onclick="togglePaddles()">Monitor paddles</button>
</div>
<div class="row" id="padRow" style="display:none">
  <span class="led" id="led_dit">DIT</span>
  <span class="led" id="led_dah">DAH</span>
  <span class="led" id="led_tx">TX</span>
  <span class="led" id="led_rx">RX</span>
  <span class="led" id="led_key">KEY</span>
</div>
<div id="testm" class="m"></div>

<h2>Send CW</h2>
<textarea id="txt" rows="3" placeholder="Text to send (Ctrl+Enter)"></textarea>
<div class="row"><button onclick="sendText()">Send</button></div>
<div id="tm" class="m"></div>

<script>
function m(id,t,ok){var e=document.getElementById(id);e.textContent=t;e.style.color=ok?'#0f0':'#f55';}

fetch('/config').then(r=>r.json()).then(d=>{
  function set(id,v,did,fmt){
    var el=document.getElementById(id);if(!el)return;
    el.value=v;
    if(did)document.getElementById(did).textContent=fmt?fmt(v):v;
  }
  set('wpm',d.wpm,'wpmv');
  set('freq',d.freq,'freqv');
  set('weight',d.weight,'weightv',v=>(v/100).toFixed(1)+'x');
  set('vol',d.volume,'volv',v=>v+'%');
  ['pin_dit','pin_dah','pin_tx','pin_rx'].forEach(k=>{
    var el=document.getElementById(k);
    if(el&&d[k]!==undefined)el.value=d[k];
  });
}).catch(()=>{});

async function saveAll(){
  function pin(id){return parseInt(document.getElementById(id).value)||0;}
  var body=JSON.stringify({
    wpm:parseInt(document.getElementById('wpm').value),
    freq:parseInt(document.getElementById('freq').value),
    weight:parseInt(document.getElementById('weight').value),
    volume:parseInt(document.getElementById('vol').value),
    pin_dit:pin('pin_dit'),pin_dah:pin('pin_dah'),
    pin_tx:pin('pin_tx'),pin_rx:pin('pin_rx')
  });
  try{
    var r=await fetch('/config',{method:'POST',headers:{'Content-Type':'application/json'},body:body});
    if(r.ok){
      var d=await r.json();
      document.getElementById('wpm').value=d.wpm;
      document.getElementById('wpmv').textContent=d.wpm;
      document.getElementById('freq').value=d.freq;
      document.getElementById('freqv').textContent=d.freq;
      document.getElementById('weight').value=d.weight;
      document.getElementById('weightv').textContent=(d.weight/100).toFixed(1)+'x';
      document.getElementById('vol').value=d.volume;
      document.getElementById('volv').textContent=d.volume+'%';
      ['pin_dit','pin_dah','pin_tx','pin_rx'].forEach(k=>{
        if(d[k]!==undefined)document.getElementById(k).value=d[k];
      });
      m('sm','Settings applied',true);
    }else m('sm','Error '+r.status,false);
  }catch(e){m('sm',''+e,false);}
}

async function testTone(){
  try{
    var r=await fetch('/test',{method:'POST'});
    m('testm',r.ok?'Tone sent':'Error '+r.status,r.ok);
  }catch(e){m('testm',''+e,false);}
}

async function sendText(){
  var t=document.getElementById('txt').value.trim();
  if(!t)return;
  m('tm','Sending...',true);
  try{
    var r=await fetch('/send',{method:'POST',headers:{'Content-Type':'text/plain'},body:t});
    m('tm',r.ok?'Queued':(r.status===503?'Busy - retry':'Error '+r.status),r.ok);
  }catch(e){m('tm',''+e,false);}
}

document.getElementById('txt').addEventListener('keydown',e=>{
  if(e.key==='Enter'&&e.ctrlKey)sendText();
});

var padTimer=null;
function togglePaddles(){
  if(padTimer){
    clearInterval(padTimer);padTimer=null;
    document.getElementById('padRow').style.display='none';
    document.getElementById('padBtn').textContent='Monitor paddles';
    return;
  }
  document.getElementById('padRow').style.display='flex';
  document.getElementById('padBtn').textContent='Stop monitoring';
  padTimer=setInterval(pollPaddles,80);
}
async function pollPaddles(){
  try{
    var r=await fetch('/paddles');var d=await r.json();
    ['dit','dah','tx','rx'].forEach(k=>{
      var el=document.getElementById('led_'+k);
      if(d[k])el.classList.add('on');else el.classList.remove('on');
    });
    var key=document.getElementById('led_key');
    if(d.keyed)key.classList.add('on');else key.classList.remove('on');
  }catch(e){}
}
</script>
</body>
</html>"""

if __name__ == "__main__":
    main()
