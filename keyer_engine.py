"""Iambic Mode-B CW keyer engine.

Pure logic -- no I/O.  Call tick() once per millisecond with the
current paddle states and it returns whether the key should be down.

Morse Timing (PARIS standard)
------------------------------
The word "PARIS" contains exactly 50 dit-units.
At *W* words per minute the fundamental dit duration is:

    dit_duration = 60 / (50 * W) = 1.2 / W   seconds

Element durations measured in dit-units:

    dit                1 unit   =  1.2 / W  s
    dah                3 units  =  3.6 / W  s   (adjustable via weight)
    intra-char gap     1 unit   =  1.2 / W  s
    inter-char gap     3 units  =  3.6 / W  s
    inter-word gap     7 units  =  8.4 / W  s

The *weight* parameter scales the dah length:
    weight = 300 -> dah = 3.0 * dit  (standard)
    weight = 350 -> dah = 3.5 * dit  (heavy)
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


# ---------------------------------------------------------------------------
#  Keyer state machine
# ---------------------------------------------------------------------------
class Keyer:
    """Iambic Mode-B keyer.

    States:
        IDLE    - waiting for a paddle press
        SENDING - tone on (dit or dah)
        SPACING - inter-element silence

    Mode-B behaviour: the opposite paddle is latched into *memory*
    only during the SENDING phase.  When both paddles are squeezed
    and then released, the keyer finishes the current element plus
    one alternation -- the hallmark of Mode B.
    """

    IDLE, SENDING, SPACING = 0, 1, 2

    def __init__(self, wpm=20, weight=300):
        self.state = self.IDLE
        self.element = None          # 'dit' or 'dah'
        self.mem = None              # opposite-paddle memory
        self.elapsed = 0.0
        self.duration = 0.0
        self._update_timing(wpm, weight)

    # -- timing -----------------------------------------------------------

    def _update_timing(self, wpm, weight):
        dit_s = 1.2 / max(wpm, 1)   # seconds per dit
        self.dit_len = dit_s
        self.dah_len = dit_s * weight / 100.0
        self.gap_len = dit_s         # intra-element gap = 1 dit

    def update(self, wpm, weight):
        """Re-calculate timing (call when WPM or weight changes)."""
        self._update_timing(wpm, weight)

    def reset(self):
        """Force keyer back to IDLE."""
        self.state = self.IDLE
        self.element = None
        self.mem = None

    # -- element selection ------------------------------------------------

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

    # -- main tick --------------------------------------------------------

    def tick(self, dt, dit, dah):
        """Advance the keyer by *dt* seconds.

        Returns True when the key (tone) should be ON.
        """
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
            # Latch opposite paddle (Mode-B)
            if self.element == 'dit' and dah:
                self.mem = 'dah'
            elif self.element == 'dah' and dit:
                self.mem = 'dit'
            self.elapsed += dt
            if self.elapsed < self.duration:
                return True
            # -> spacing
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
#  Text -> element list
# ---------------------------------------------------------------------------
def text_to_elements(text, wpm=20, weight=300):
    """Convert *text* to a list of ``('on'|'off', seconds)`` tuples.

    Suitable for feeding into the send-queue so the keyer can play
    back arbitrary text as Morse code.
    """
    dit_s = 1.2 / max(wpm, 1)
    dah_s = dit_s * weight / 100.0
    gap_s = dit_s

    elements = []
    prev_char = False

    for ch in text.upper():
        if ch == ' ':
            if prev_char:
                elements.append(('off', gap_s * 7))   # word gap
            prev_char = False
            continue

        code = MORSE.get(ch)
        if not code:
            continue

        if prev_char:
            elements.append(('off', gap_s * 3))        # inter-character gap

        for j, sym in enumerate(code):
            if j > 0:
                elements.append(('off', gap_s))        # intra-character gap
            elements.append(('on', dit_s if sym == '.' else dah_s))

        prev_char = True

    return elements
