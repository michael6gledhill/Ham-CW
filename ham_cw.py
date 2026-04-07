#!/usr/bin/env python3
"""ham-cw: Iambic CW keyer for Raspberry Pi with GPIO PWM sidetone."""

import json
import pathlib
import signal
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import RPi.GPIO as IO
    _HAS_GPIO = True
except ImportError:
    IO = None
    _HAS_GPIO = False

# ---------------------------------------------------------------------------
#  Morse code table
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
    '.': '.-.-.-', ',': '--..--', '?': '..--..', '/': '-..-.', '=': '-...-',
}

# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------
CONFIG_PATH = pathlib.Path.home() / ".ham-cw.conf"

DEFAULTS = {
    "wpm": 20,
    "freq": 700,
    "weight": 300,
    "volume": 70,
    "pin_dit": 27,
    "pin_dah": 22,
    "pin_tx": 5,
    "pin_rx": 6,
    "pin_spk_pos": 20,
    "pin_spk_neg": 21,
    "pin_ptt": 16,
}

_config = dict(DEFAULTS)
_lock = threading.Lock()
_shutdown = threading.Event()


def _clamp(v, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return lo


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
    try:
        vals = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return get_config()
    with _lock:
        if "wpm"    in vals: _config["wpm"]    = _clamp(vals["wpm"], 5, 60)
        if "freq"   in vals: _config["freq"]   = _clamp(vals["freq"], 200, 2000)
        if "weight" in vals: _config["weight"] = _clamp(vals["weight"], 200, 500)
        if "volume" in vals: _config["volume"] = _clamp(vals["volume"], 0, 100)
        if "pin_dit"     in vals: _config["pin_dit"]     = _clamp(vals["pin_dit"], 0, 27)
        if "pin_dah"     in vals: _config["pin_dah"]     = _clamp(vals["pin_dah"], 0, 27)
        if "pin_tx"      in vals: _config["pin_tx"]      = _clamp(vals["pin_tx"], 0, 27)
        if "pin_rx"      in vals: _config["pin_rx"]      = _clamp(vals["pin_rx"], 0, 27)
        if "pin_spk_pos" in vals: _config["pin_spk_pos"] = _clamp(vals["pin_spk_pos"], 0, 27)
        if "pin_spk_neg" in vals: _config["pin_spk_neg"] = _clamp(vals["pin_spk_neg"], 0, 27)
        if "pin_ptt"     in vals: _config["pin_ptt"]     = _clamp(vals["pin_ptt"], 0, 27)
        result = dict(_config)
    save_config()
    return result


# ---------------------------------------------------------------------------
#  Iambic Keyer (Mode-B)
# ---------------------------------------------------------------------------
class Keyer:
    IDLE, SENDING, SPACING = 0, 1, 2

    def __init__(self, cfg):
        self.state = self.IDLE
        self.element = None
        self.mem = None
        self.elapsed = 0.0
        self.duration = 0.0
        self.update(cfg)

    def update(self, cfg):
        dit_s = 1.2 / cfg["wpm"]
        self.dit_len = dit_s
        self.dah_len = dit_s * cfg["weight"] / 100.0
        self.gap_len = dit_s

    def _pick_live(self, dit, dah):
        if dit and dah:
            return 'dah' if self.element == 'dit' else 'dit'
        if dit:
            return 'dit'
        if dah:
            return 'dah'
        return None

    def _pick_mem(self, dit, dah):
        m = self.mem
        self.mem = None
        if m:
            return m
        return self._pick_live(dit, dah)

    def tick(self, dt, dit, dah):
        """Advance keyer by dt seconds. Returns True if key is down."""
        if self.state == self.IDLE:
            nxt = self._pick_live(dit, dah)
            if nxt is None:
                return False
            self.element = nxt
            self.duration = self.dit_len if nxt == 'dit' else self.dah_len
            self.elapsed = 0.0
            self.state = self.SENDING
            return True

        if self.state == self.SENDING:
            if self.element == 'dit' and dah:
                self.mem = 'dah'
            elif self.element == 'dah' and dit:
                self.mem = 'dit'
            self.elapsed += dt
            if self.elapsed < self.duration:
                return True
            self.elapsed = 0.0
            self.duration = self.gap_len
            self.state = self.SPACING
            return False

        if self.state == self.SPACING:
            self.elapsed += dt
            if self.elapsed < self.duration:
                return False
            nxt = self._pick_mem(dit, dah)
            if nxt is None:
                self.state = self.IDLE
                return False
            self.element = nxt
            self.duration = self.dit_len if nxt == 'dit' else self.dah_len
            self.elapsed = 0.0
            self.state = self.SENDING
            return True

        return False


# ---------------------------------------------------------------------------
#  GPIO speaker (PWM sidetone)
# ---------------------------------------------------------------------------
_pwm = None
_pwm_pin = -1


def _speaker_on(pin, freq, volume):
    global _pwm, _pwm_pin
    if not _HAS_GPIO:
        return
    duty = max(0.0, min(50.0, volume / 2.0))
    if _pwm is not None and _pwm_pin == pin:
        try:
            _pwm.ChangeFrequency(max(1, freq))
            _pwm.ChangeDutyCycle(duty)
            return
        except Exception:
            _pwm = None
    _speaker_off()
    try:
        _pwm = IO.PWM(pin, max(1, freq))
        _pwm.start(duty)
        _pwm_pin = pin
    except Exception:
        _pwm = None


def _speaker_off():
    global _pwm, _pwm_pin
    if _pwm is not None:
        try:
            _pwm.stop()
        except Exception:
            pass
        _pwm = None
        _pwm_pin = -1


# ---------------------------------------------------------------------------
#  GPIO helpers
# ---------------------------------------------------------------------------
def setup_pins(cfg):
    if not _HAS_GPIO:
        return
    IO.setmode(IO.BCM)
    IO.setwarnings(False)
    for pin in [cfg["pin_dit"], cfg["pin_dah"], cfg["pin_tx"], cfg["pin_rx"]]:
        IO.setup(pin, IO.IN, pull_up_down=IO.PUD_UP)
    IO.setup(cfg["pin_spk_pos"], IO.OUT, initial=IO.LOW)
    IO.setup(cfg["pin_spk_neg"], IO.OUT, initial=IO.LOW)
    IO.setup(cfg["pin_ptt"], IO.OUT, initial=IO.LOW)


def read_pin(pin):
    if not _HAS_GPIO:
        return False
    return IO.input(pin) == 0   # active-low


# ---------------------------------------------------------------------------
#  Text-to-CW element list
# ---------------------------------------------------------------------------
def _text_to_elements(text, cfg):
    dit_s = 1.2 / cfg["wpm"]
    dah_s = dit_s * cfg["weight"] / 100.0
    gap_s = dit_s
    els = []
    prev_char = False
    for ch in text.upper():
        if ch == ' ':
            if prev_char:
                els.append(('off', gap_s * 4))     # word gap (7 - 3 already)
            prev_char = False
            continue
        code = MORSE.get(ch)
        if not code:
            continue
        if prev_char:
            els.append(('off', gap_s * 3))          # inter-char gap
        for j, sym in enumerate(code):
            if j > 0:
                els.append(('off', gap_s))           # intra-char gap
            els.append(('on', dit_s if sym == '.' else dah_s))
        prev_char = True
    return els


# ---------------------------------------------------------------------------
#  Send queue (test tone, text, IP announce)
# ---------------------------------------------------------------------------
_send_queue = []
_send_ptt = False
_sq_lock = threading.Lock()


def _enqueue(elements, use_ptt=False):
    global _send_ptt
    with _sq_lock:
        _send_queue.clear()
        _send_queue.extend(elements)
        _send_ptt = use_ptt


def enqueue_test():
    _enqueue([('on', 0.5)], use_ptt=False)


def enqueue_text(text, cfg):
    els = _text_to_elements(text, cfg)
    if els:
        _enqueue(els, use_ptt=True)


def enqueue_ip(cfg):
    try:
        ip = subprocess.check_output(
            ["hostname", "-I"], text=True, timeout=2
        ).split()[0]
    except Exception:
        ip = "0.0.0.0"
    els = _text_to_elements(ip, cfg)
    if els:
        _enqueue(els, use_ptt=False)


# ---------------------------------------------------------------------------
#  HTTP handler + embedded web UI
# ---------------------------------------------------------------------------
_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ham-cw</title><style>
body{background:#1a1a2e;color:#eee;font-family:sans-serif;max-width:480px;margin:0 auto;padding:1rem}
h1{margin:0 0 .5rem;font-size:1.3rem}
h2{margin:1rem 0 .3rem;font-size:1rem;color:#aaa;border-bottom:1px solid #333;padding-bottom:.2rem}
.row{display:flex;align-items:center;gap:.5rem;margin:.3rem 0}
.row label{min-width:120px;font-size:.85rem}.row input[type=range]{flex:1}
.val{min-width:50px;text-align:right;font-size:.85rem;font-weight:bold}
.num{width:60px;text-align:center;background:#111;color:#eee;border:1px solid #444;border-radius:4px;padding:4px}
button{background:#16213e;color:#eee;border:1px solid #0f3460;border-radius:6px;padding:.4rem 1.2rem;cursor:pointer;font-size:.9rem}
button:hover{background:#0f3460}
.m{font-size:.8rem;margin:.3rem 0;min-height:1.2em}
textarea{width:100%;background:#111;color:#eee;border:1px solid #444;border-radius:4px;padding:.4rem;font-family:monospace;resize:vertical;box-sizing:border-box}
.pill{display:inline-block;padding:2px 10px;border-radius:10px;font-size:.8rem;font-weight:bold}
.on{background:#0f0;color:#000}.off{background:#333;color:#666}
</style></head><body>
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
  <label>Volume</label>
  <input id="volume" type="range" min="0" max="100" value="70"
         oninput="document.getElementById('volumev').textContent=this.value+'%'">
  <span class="val" id="volumev">70%</span>
</div>

<h2>GPIO pins (BCM)</h2>
<div class="row"><label>DIT paddle</label><input id="pin_dit" type="number" min="0" max="27" value="27" class="num"></div>
<div class="row"><label>DAH paddle</label><input id="pin_dah" type="number" min="0" max="27" value="22" class="num"></div>
<div class="row"><label>TX switch</label><input id="pin_tx" type="number" min="0" max="27" value="5" class="num"></div>
<div class="row"><label>RX switch</label><input id="pin_rx" type="number" min="0" max="27" value="6" class="num"></div>
<div class="row"><label>Speaker +</label><input id="pin_spk_pos" type="number" min="0" max="27" value="20" class="num"></div>
<div class="row"><label>Speaker &minus;</label><input id="pin_spk_neg" type="number" min="0" max="27" value="21" class="num"></div>
<div class="row"><label>PTT output</label><input id="pin_ptt" type="number" min="0" max="27" value="16" class="num"></div>
<p style="font-size:.75rem;color:#060;margin:.3rem 0 0">Inputs are active-low with pull-ups. PTT goes HIGH when keying. Speaker uses PWM square wave. Hold both paddles 3&nbsp;s to send IP as CW.</p>

<div class="row"><button onclick="saveAll()">Apply settings</button></div>
<div id="sm" class="m"></div>

<h2>Test tone</h2>
<div class="row"><button onclick="testTone()">Test</button></div>
<div id="testm" class="m"></div>

<h2>Paddles</h2>
<div class="row" style="gap:1rem">
  <span>DIT <span id="dit" class="pill off">-</span></span>
  <span>DAH <span id="dah" class="pill off">-</span></span>
  <span id="txrx" class="pill off">RX</span>
</div>

<h2>Send CW</h2>
<textarea id="txt" rows="3" placeholder="Text to send (letters, numbers, punctuation)"></textarea>
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
  set('volume',d.volume,'volumev',v=>v+'%');
  ['pin_dit','pin_dah','pin_tx','pin_rx','pin_spk_pos','pin_spk_neg','pin_ptt'].forEach(k=>{
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
    volume:parseInt(document.getElementById('volume').value),
    pin_dit:pin('pin_dit'),pin_dah:pin('pin_dah'),
    pin_tx:pin('pin_tx'),pin_rx:pin('pin_rx'),
    pin_spk_pos:pin('pin_spk_pos'),pin_spk_neg:pin('pin_spk_neg'),
    pin_ptt:pin('pin_ptt')
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
      document.getElementById('volume').value=d.volume;
      document.getElementById('volumev').textContent=d.volume+'%';
      ['pin_dit','pin_dah','pin_tx','pin_rx','pin_spk_pos','pin_spk_neg','pin_ptt'].forEach(k=>{
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
    m('tm',r.ok?'Queued':'Error '+r.status,r.ok);
  }catch(e){m('tm',''+e,false);}
}

(function poll(){
  fetch('/paddles').then(r=>r.json()).then(d=>{
    function p(id,v){var e=document.getElementById(id);e.className='pill '+(v?'on':'off');e.textContent=v?'ON':'-';}
    p('dit',d.dit);
    p('dah',d.dah);
    var tx=document.getElementById('txrx');
    tx.className='pill '+(d.tx?'on':'off');
    tx.textContent=d.tx?'TX':'RX';
  }).catch(()=>{});
  setTimeout(poll,200);
})();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _headers(self, code=200, ct="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            self._headers(ct="text/html")
            self.wfile.write(_HTML.encode())
        elif self.path == "/config":
            self._headers()
            self.wfile.write(json.dumps(get_config()).encode())
        elif self.path == "/paddles":
            cfg = get_config()
            self._headers()
            self.wfile.write(json.dumps({
                "dit": read_pin(cfg["pin_dit"]),
                "dah": read_pin(cfg["pin_dah"]),
                "tx":  read_pin(cfg["pin_tx"]),
            }).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        if self.path == "/config":
            result = apply_config(body)
            self._headers()
            self.wfile.write(json.dumps(result).encode())
        elif self.path == "/test":
            enqueue_test()
            self._headers()
            self.wfile.write(b'{"ok":true}')
        elif self.path == "/send":
            text = body.decode("utf-8", errors="replace").strip()
            if text:
                enqueue_text(text, get_config())
            self._headers()
            self.wfile.write(b'{"ok":true}')
        else:
            self.send_error(404)


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------
def main():
    load_config()
    cfg = get_config()

    # GPIO
    setup_pins(cfg)
    cur_pins = tuple(cfg[k] for k in [
        "pin_dit", "pin_dah", "pin_tx", "pin_rx",
        "pin_spk_pos", "pin_spk_neg", "pin_ptt"])

    # Signals
    def on_sig(sig, frame):
        _shutdown.set()
    signal.signal(signal.SIGINT, on_sig)
    signal.signal(signal.SIGTERM, on_sig)

    # HTTP server
    srv = HTTPServer(("", 8080), Handler)
    srv.allow_reuse_address = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print("ham-cw: http server on :8080")

    # Keyer
    keyer = Keyer(cfg)
    DT = 0.001
    prev_key = False
    prev_ptt = False
    both_time = 0.0

    # Send-queue state
    sq_action = None
    sq_end = 0.0

    try:
        while not _shutdown.is_set():
            now = time.monotonic()
            cfg = get_config()
            keyer.update(cfg)

            # Hot-reload GPIO pins
            new_pins = tuple(cfg[k] for k in [
                "pin_dit", "pin_dah", "pin_tx", "pin_rx",
                "pin_spk_pos", "pin_spk_neg", "pin_ptt"])
            if new_pins != cur_pins:
                _speaker_off()
                if _HAS_GPIO:
                    IO.cleanup()
                setup_pins(cfg)
                cur_pins = new_pins
                prev_key = False
                prev_ptt = False

            # Read inputs
            dit = read_pin(cfg["pin_dit"])
            dah = read_pin(cfg["pin_dah"])
            tx_mode = read_pin(cfg["pin_tx"])

            # Hold both paddles 3 s -> announce IP as CW
            if dit and dah:
                both_time += DT
                if both_time >= 3.0:
                    both_time = 0.0
                    enqueue_ip(cfg)
            else:
                both_time = 0.0

            # Process send queue
            if sq_action is not None and now >= sq_end:
                sq_action = None
            if sq_action is None:
                with _sq_lock:
                    if _send_queue:
                        act, dur = _send_queue.pop(0)
                        sq_action = act
                        sq_end = now + dur

            # Determine key state and PTT desire
            if sq_action is not None:
                key_down = (sq_action == 'on')
                ptt = key_down and _send_ptt and tx_mode
            elif tx_mode:
                key_down = keyer.tick(DT, dit, dah)
                ptt = key_down
            else:
                key_down = False
                ptt = False
                if keyer.state != Keyer.IDLE:
                    keyer.state = Keyer.IDLE
                    keyer.mem = None

            # Update speaker
            if key_down and not prev_key:
                _speaker_on(cfg["pin_spk_pos"], cfg["freq"], cfg["volume"])
            elif not key_down and prev_key:
                _speaker_off()
            prev_key = key_down

            # Update PTT
            if ptt != prev_ptt:
                if _HAS_GPIO:
                    IO.output(cfg["pin_ptt"], IO.HIGH if ptt else IO.LOW)
                prev_ptt = ptt

            # Sleep remainder of tick
            elapsed = time.monotonic() - now
            remaining = DT - elapsed
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        pass
    finally:
        _speaker_off()
        if _HAS_GPIO:
            try:
                IO.output(cfg["pin_ptt"], IO.LOW)
            except Exception:
                pass
            IO.cleanup()
        srv.shutdown()
        print("\nham-cw: stopped.")


if __name__ == "__main__":
    main()
