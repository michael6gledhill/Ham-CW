"""Morse code tables, timing logic, and iambic keyer.

Pre-computes timing tables at startup for performance.
Standard timing: dit = 1200 / WPM milliseconds.
"""

# ---------------------------------------------------------------------------
#  Morse look-up table
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
    '=': '-...-',  ':': '---...', ';': '-.-.-.', '+': '.-.-.',
    '-': '-....-', '_': '..--.-', '"': '.-..-.', "'": '.----.',
    '(': '-.--.',  ')': '-.--.-', '!': '-.-.--', '@': '.--.-.',
}


def dit_duration(wpm):
    """Standard dit duration in seconds: 1200ms / WPM."""
    return 1.2 / max(wpm, 1)


# ---------------------------------------------------------------------------
#  Pre-computed timing table (rebuilt when WPM changes)
# ---------------------------------------------------------------------------
_timing_cache = {}


def get_timing(wpm):
    """Return (dit_s, dah_s, gap_s) for a given WPM, with caching."""
    if wpm not in _timing_cache:
        d = dit_duration(wpm)
        _timing_cache[wpm] = (d, d * 3.0, d)
    return _timing_cache[wpm]


# ---------------------------------------------------------------------------
#  Iambic Mode-B keyer state machine
# ---------------------------------------------------------------------------
class Keyer:
    """Iambic Mode-B keyer with deadline-based timing.

    Pure logic -- no I/O.  Call tick(now, dit, dah) where *now* is
    time.monotonic().  Returns True when the tone should be ON.

    Uses absolute deadlines instead of elapsed-time accumulation so
    that polling jitter never makes elements longer or shorter than
    they should be.  Deadlines chain from one to the next, so any
    overshoot in one phase is automatically compensated in the next.

    States:
        IDLE    -- waiting for a paddle press
        SENDING -- tone on (dit or dah)
        SPACING -- inter-element silence

    Mode-B behaviour: the opposite paddle is latched into *memory*
    only during the SENDING phase.  When both paddles are squeezed
    and then released, the keyer finishes the current element plus
    one alternation.
    """

    IDLE, SENDING, SPACING = 0, 1, 2

    def __init__(self, wpm=20):
        self.state = self.IDLE
        self.element = None
        self.mem = None
        self.deadline = 0.0
        self._update_timing(wpm)

    def _update_timing(self, wpm):
        dit_s, dah_s, gap_s = get_timing(wpm)
        self.dit_len = dit_s
        self.dah_len = dah_s
        self.gap_len = gap_s

    def update(self, wpm):
        """Recalculate timing (call when WPM changes)."""
        self._update_timing(wpm)

    def reset(self):
        """Force keyer back to IDLE."""
        self.state = self.IDLE
        self.element = None
        self.mem = None

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
        return m if m else self._pick_live(dit, dah)

    def tick(self, now, dit, dah):
        """Advance keyer at monotonic time *now*.  Returns True = tone ON."""
        if self.state == self.IDLE:
            nxt = self._pick_live(dit, dah)
            if nxt is None:
                return False
            self.element = nxt
            dur = self.dit_len if nxt == 'dit' else self.dah_len
            self.deadline = now + dur
            self.state = self.SENDING
            return True

        if self.state == self.SENDING:
            if self.element == 'dit' and dah:
                self.mem = 'dah'
            elif self.element == 'dah' and dit:
                self.mem = 'dit'
            if now < self.deadline:
                return True
            # Element finished -> inter-element gap
            # Chain from previous deadline so jitter doesn't accumulate
            self.deadline += self.gap_len
            self.state = self.SPACING
            return False

        if self.state == self.SPACING:
            if now < self.deadline:
                return False
            nxt = self._pick_mem(dit, dah)
            if nxt is None:
                self.state = self.IDLE
                return False
            self.element = nxt
            dur = self.dit_len if nxt == 'dit' else self.dah_len
            # Chain from gap deadline for precise total cycle time
            self.deadline += dur
            self.state = self.SENDING
            return True

        return False


# ---------------------------------------------------------------------------
#  Text -> element list
# ---------------------------------------------------------------------------
def text_to_elements(text, wpm=20):
    """Convert *text* to a list of ('on'|'off', seconds) tuples."""
    dit_s, dah_s, gap_s = get_timing(wpm)

    elements = []
    prev_char = False

    for ch in text.upper():
        if ch == ' ':
            if prev_char:
                elements.append(('off', gap_s * 7))
            prev_char = False
            continue

        code = MORSE.get(ch)
        if not code:
            continue

        if prev_char:
            elements.append(('off', gap_s * 3))

        for j, sym in enumerate(code):
            if j > 0:
                elements.append(('off', gap_s))
            elements.append(('on', dit_s if sym == '.' else dah_s))

        prev_char = True

    return elements
