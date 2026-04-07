"""Touchscreen GUI for ham-cw keyer.

Designed for the official Raspberry Pi 7-inch display (800 x 480).
Dark theme, large touch targets, no keyboard required for normal
operation.  Falls back gracefully if tkinter or a display is
unavailable.
"""

import tkinter as tk

# ---------------------------------------------------------------------------
#  Colour palette
# ---------------------------------------------------------------------------
BG       = '#1a1a2e'
FG       = '#e0e0e0'
BG_ROW   = '#16213e'
BG_SEL   = '#0f3460'
ACCENT   = '#e94560'
GREEN    = '#00cc66'
DIM      = '#444444'
BG_BTN   = '#16213e'
BG_MINUS = '#2a1a3e'
BG_PLUS  = '#1a3e2a'

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
_PARAM_LABEL = {'wpm': 'WPM', 'freq': 'Frequency', 'volume': 'Volume'}
_PARAM_FMT   = {
    'wpm':    lambda v: str(v),
    'freq':   lambda v: f'{v} Hz',
    'volume': lambda v: f'{v}%',
}


# ---------------------------------------------------------------------------
#  GUI class
# ---------------------------------------------------------------------------
class KeyerGui:
    """Build and manage the tkinter interface.

    *app* must expose:
        app.get_config()          -> dict
        app.selected_param        -> str   ('wpm' | 'freq' | 'volume')
        app.select_param(name)
        app.adjust(direction)     -> None  (direction = +1 / -1)
        app.test_tone()
        app.send_text(text)
        app.key_down              -> bool
        app.dit                   -> bool
        app.dah                   -> bool
    """

    PARAMS = ('wpm', 'freq', 'volume')

    def __init__(self, root, app):
        self.root = root
        self.app = app

        root.title('HAM-CW')
        root.configure(bg=BG)
        root.attributes('-fullscreen', True)

        # Escape exits full-screen (handy during development)
        root.bind('<Escape>',
                  lambda _e: root.attributes('-fullscreen', False))

        self._build_title()
        self._build_params()
        self._build_adj_buttons()
        self._build_indicators()
        self._build_send_section()

        self._poll()

    # -- widget builders --------------------------------------------------

    def _build_title(self):
        f = tk.Frame(self.root, bg=BG)
        f.pack(fill='x', padx=16, pady=(12, 0))
        tk.Label(f, text='HAM-CW KEYER', font=('Arial', 22, 'bold'),
                 bg=BG, fg=FG).pack(side='left')
        self._tx_lbl = tk.Label(f, text='IDLE', font=('Arial', 18, 'bold'),
                                bg=BG, fg=DIM)
        self._tx_lbl.pack(side='right')

    def _build_params(self):
        self._param_frames = {}
        self._param_vals = {}

        for p in self.PARAMS:
            f = tk.Frame(self.root, bg=BG_ROW, cursor='hand2',
                         highlightthickness=3, highlightbackground='#333')
            f.pack(fill='x', padx=20, pady=4)
            f.bind('<Button-1>', lambda _e, _p=p: self.app.select_param(_p))

            lbl = tk.Label(f, text=_PARAM_LABEL[p], font=('Arial', 18),
                           bg=BG_ROW, fg='#aaa', anchor='w', padx=20, pady=12)
            lbl.pack(side='left', fill='x', expand=True)
            lbl.bind('<Button-1>', lambda _e, _p=p: self.app.select_param(_p))

            val = tk.Label(f, text='--', font=('Arial', 24, 'bold'),
                           bg=BG_ROW, fg=FG, anchor='e', padx=20, pady=12)
            val.pack(side='right')
            val.bind('<Button-1>', lambda _e, _p=p: self.app.select_param(_p))

            self._param_frames[p] = f
            self._param_vals[p] = val

    def _build_adj_buttons(self):
        f = tk.Frame(self.root, bg=BG)
        f.pack(fill='x', padx=20, pady=8)

        # Minus button  (with auto-repeat on hold)
        self._btn_minus = tk.Button(
            f, text='\u2014', font=('Arial', 30, 'bold'),
            bg=BG_MINUS, fg=FG, activebackground='#4a2a5e',
            relief='flat', bd=0)
        self._btn_minus.pack(side='left', expand=True, fill='x', padx=(0, 6),
                             ipady=6)
        self._btn_minus.bind('<ButtonPress-1>', lambda _e: self._start_repeat(-1))
        self._btn_minus.bind('<ButtonRelease-1>', lambda _e: self._stop_repeat())

        # Plus button
        self._btn_plus = tk.Button(
            f, text='+', font=('Arial', 30, 'bold'),
            bg=BG_PLUS, fg=FG, activebackground='#2a5e3a',
            relief='flat', bd=0)
        self._btn_plus.pack(side='right', expand=True, fill='x', padx=(6, 0),
                            ipady=6)
        self._btn_plus.bind('<ButtonPress-1>', lambda _e: self._start_repeat(1))
        self._btn_plus.bind('<ButtonRelease-1>', lambda _e: self._stop_repeat())

        self._repeat_id = None

    def _build_indicators(self):
        f = tk.Frame(self.root, bg=BG)
        f.pack(fill='x', padx=24, pady=4)

        self._dit_lbl = tk.Label(f, text='\u25cf DIT', font=('Arial', 16, 'bold'),
                                 bg=BG, fg=DIM)
        self._dit_lbl.pack(side='left', padx=(0, 30))

        self._dah_lbl = tk.Label(f, text='\u25cf DAH', font=('Arial', 16, 'bold'),
                                 bg=BG, fg=DIM)
        self._dah_lbl.pack(side='left')

    def _build_send_section(self):
        f = tk.Frame(self.root, bg=BG)
        f.pack(fill='x', padx=20, pady=(8, 12), side='bottom')

        tk.Button(f, text='Test Tone', font=('Arial', 15),
                  bg=BG_BTN, fg=FG, activebackground='#0f3460',
                  relief='flat', padx=16, pady=8,
                  command=self.app.test_tone).pack(side='left')

        tk.Button(f, text='Send', font=('Arial', 15),
                  bg=BG_BTN, fg=FG, activebackground='#0f3460',
                  relief='flat', padx=16, pady=8,
                  command=self._on_send).pack(side='right')

        self._txt = tk.Entry(f, font=('Arial', 15), bg='#111', fg=FG,
                             insertbackground=FG, relief='flat', bd=2)
        self._txt.pack(side='right', fill='x', expand=True, padx=10)

    # -- auto-repeat for +/- buttons--------------------------------------

    def _start_repeat(self, direction):
        self.app.adjust(direction)
        self._repeat_id = self.root.after(400, self._repeat, direction)

    def _repeat(self, direction):
        self.app.adjust(direction)
        self._repeat_id = self.root.after(120, self._repeat, direction)

    def _stop_repeat(self):
        if self._repeat_id is not None:
            self.root.after_cancel(self._repeat_id)
            self._repeat_id = None

    # -- send CW ----------------------------------------------------------

    def _on_send(self):
        text = self._txt.get().strip()
        if text:
            self.app.send_text(text)
            self._txt.delete(0, 'end')

    # -- periodic display update ------------------------------------------

    def _poll(self):
        cfg = self.app.get_config()
        sel = self.app.selected_param

        # Parameter values & selection highlight
        for p in self.PARAMS:
            self._param_vals[p].config(text=_PARAM_FMT[p](cfg[p]))
            if p == sel:
                self._param_frames[p].config(highlightbackground='#4488ff')
                self._param_vals[p].config(fg='#fff')
            else:
                self._param_frames[p].config(highlightbackground='#333')
                self._param_vals[p].config(fg='#aaa')

        # TX / keying indicator
        if self.app.key_down:
            self._tx_lbl.config(text='\u25cf KEYING', fg=ACCENT)
        else:
            self._tx_lbl.config(text='IDLE', fg=DIM)

        # Paddle indicators
        self._dit_lbl.config(fg=GREEN if self.app.dit else DIM)
        self._dah_lbl.config(fg=GREEN if self.app.dah else DIM)

        self.root.after(50, self._poll)     # 20 Hz refresh
