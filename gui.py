"""Touchscreen GUI for ham-cw keyer (Pi 4 + 7" display).

Fullscreen dark-theme interface with parameter controls,
status indicators, and text-mode CW entry.
"""

import tkinter as tk
import config

# -- Colour palette -------------------------------------------------------
BG       = '#1a1a2e'
FG       = '#e0e0e0'
BTN_BG   = '#333355'
BTN_FG   = '#e0e0e0'
BTN_ACT  = '#555577'
SEL_BG   = '#00ff88'
TX_ON    = '#ff4444'
TX_OFF   = '#444444'
KEY_ON   = '#ffcc00'
KEY_OFF  = '#333333'
MODE_TX  = '#ff8800'
MODE_TXT = '#00aaff'
ENTRY_BG = '#222244'
SEND_BG  = '#225522'
SEND_ACT = '#338833'
STOP_BG  = '#552222'
STOP_ACT = '#883333'


class Gui:
    """Touchscreen GUI for ham-cw keyer."""

    def __init__(self, root, *, on_adjust, on_select, on_send,
                 on_stop, on_test, get_state):
        self._root = root
        self._on_adjust = on_adjust
        self._on_select = on_select
        self._on_send = on_send
        self._on_stop = on_stop
        self._on_test = on_test
        self._get_state = get_state

        root.title('ham-cw')
        root.configure(bg=BG)
        root.attributes('-fullscreen', True)
        root.bind('<Escape>',
                  lambda e: root.attributes('-fullscreen', False))

        # Fonts
        self._f_title = ('Helvetica', 20, 'bold')
        self._f_label = ('Helvetica', 16)
        self._f_value = ('Helvetica', 22, 'bold')
        self._f_btn   = ('Helvetica', 18)
        self._f_ind   = ('Helvetica', 14)
        self._f_entry = ('Helvetica', 16)

        self._param_frames = {}
        self._param_values = {}

        self._build_header()
        self._build_params()
        self._build_indicators()
        self._build_text_area()
        self._refresh()

    # -- Header -----------------------------------------------------------

    def _build_header(self):
        hdr = tk.Frame(self._root, bg=BG, height=50)
        hdr.pack(fill='x', padx=10, pady=(10, 0))
        hdr.pack_propagate(False)

        self._mode_lbl = tk.Label(hdr, text='TX', font=self._f_title,
                                  bg=BG, fg=MODE_TX, anchor='w')
        self._mode_lbl.pack(side='left')

        self._tx_ind = tk.Label(hdr, text='  TX  ', font=self._f_title,
                                bg=TX_OFF, fg='white', padx=10)
        self._tx_ind.pack(side='left', padx=20)

        tk.Label(hdr, text='ham-cw', font=self._f_title,
                 bg=BG, fg='#666666').pack(side='right')

    # -- Parameter rows ---------------------------------------------------

    def _build_params(self):
        container = tk.Frame(self._root, bg=BG)
        container.pack(fill='both', expand=True, padx=10, pady=10)

        info = [
            ('wpm',    'WPM',    '',   0),
            ('freq',   'Freq',   'Hz', 1),
            ('volume', 'Volume', '%',  2),
        ]

        for param, label, unit, idx in info:
            frame = tk.Frame(container, bg=BG,
                             highlightthickness=3,
                             highlightbackground=BG)
            frame.pack(fill='x', pady=4)
            frame.bind('<Button-1>',
                       lambda e, i=idx: self._on_select(i))

            # Minus
            tk.Button(frame, text='\u2212', font=self._f_btn,
                      bg=BTN_BG, fg=BTN_FG, width=3,
                      activebackground=BTN_ACT,
                      command=lambda p=param: self._on_adjust(p, -1)
                      ).pack(side='left', padx=(5, 10), pady=5)

            # Label
            lbl = tk.Label(frame, text=label, font=self._f_label,
                           bg=BG, fg=FG, width=8, anchor='w')
            lbl.pack(side='left')
            lbl.bind('<Button-1>',
                     lambda e, i=idx: self._on_select(i))

            # Value
            var = tk.StringVar(value='--')
            val = tk.Label(frame, textvariable=var,
                           font=self._f_value, bg=BG, fg=FG,
                           width=6, anchor='center')
            val.pack(side='left', expand=True)
            val.bind('<Button-1>',
                     lambda e, i=idx: self._on_select(i))

            # Unit
            tk.Label(frame, text=unit, font=self._f_label,
                     bg=BG, fg='#888888', width=3).pack(side='left')

            # Plus
            tk.Button(frame, text='+', font=self._f_btn,
                      bg=BTN_BG, fg=BTN_FG, width=3,
                      activebackground=BTN_ACT,
                      command=lambda p=param: self._on_adjust(p, 1)
                      ).pack(side='right', padx=(10, 5), pady=5)

            self._param_frames[param] = frame
            self._param_values[param] = var

    # -- Status indicators ------------------------------------------------

    def _build_indicators(self):
        bar = tk.Frame(self._root, bg=BG, height=40)
        bar.pack(fill='x', padx=10)
        bar.pack_propagate(False)

        self._dit_ind = tk.Label(bar, text=' DIT ', font=self._f_ind,
                                 bg=KEY_OFF, fg='white', padx=5)
        self._dit_ind.pack(side='left', padx=5)

        self._dah_ind = tk.Label(bar, text=' DAH ', font=self._f_ind,
                                 bg=KEY_OFF, fg='white', padx=5)
        self._dah_ind.pack(side='left', padx=5)

        self._key_ind = tk.Label(bar, text=' KEY ', font=self._f_ind,
                                 bg=KEY_OFF, fg='white', padx=5)
        self._key_ind.pack(side='left', padx=5)

        tk.Button(bar, text='Test', font=self._f_ind,
                  bg=BTN_BG, fg=BTN_FG,
                  activebackground=BTN_ACT,
                  command=self._on_test).pack(side='right', padx=5)

    # -- Text entry area --------------------------------------------------

    def _build_text_area(self):
        area = tk.Frame(self._root, bg=BG, height=110)
        area.pack(fill='x', padx=10, pady=(5, 10))
        area.pack_propagate(False)

        self._text_entry = tk.Entry(area, font=self._f_entry,
                                    bg=ENTRY_BG, fg=FG,
                                    insertbackground=FG)
        self._text_entry.pack(fill='x', pady=(0, 5))
        self._text_entry.bind('<Return>',
                              lambda e: self._do_send())

        row = tk.Frame(area, bg=BG)
        row.pack(fill='x')

        tk.Button(row, text='Send', font=self._f_btn,
                  bg=SEND_BG, fg=BTN_FG, width=8,
                  activebackground=SEND_ACT,
                  command=self._do_send).pack(side='left', padx=5)

        tk.Button(row, text='Stop', font=self._f_btn,
                  bg=STOP_BG, fg=BTN_FG, width=8,
                  activebackground=STOP_ACT,
                  command=self._on_stop).pack(side='left', padx=5)

    def _do_send(self):
        text = self._text_entry.get().strip()
        if text:
            self._on_send(text)

    # -- Periodic refresh (20 Hz) -----------------------------------------

    def _refresh(self):
        try:
            state = self._get_state()
            cfg = config.get_config()
            sel = config.get_selected_param()

            # Mode label
            mode = state.get('mode', 'tx')
            if mode == 'text':
                self._mode_lbl.config(text='TEXT', fg=MODE_TXT)
            else:
                self._mode_lbl.config(text='TX', fg=MODE_TX)

            # TX indicator
            self._tx_ind.config(
                bg=TX_ON if state.get('key_down') else TX_OFF)

            # Parameter values
            self._param_values['wpm'].set(str(cfg['wpm']))
            self._param_values['freq'].set(str(cfg['freq']))
            self._param_values['volume'].set(str(cfg['volume']))

            # Highlight selected param
            for param, frame in self._param_frames.items():
                frame.config(
                    highlightbackground=SEL_BG if param == sel else BG)

            # DIT / DAH / KEY indicators
            self._dit_ind.config(
                bg=KEY_ON if state.get('dit') else KEY_OFF)
            self._dah_ind.config(
                bg=KEY_ON if state.get('dah') else KEY_OFF)
            self._key_ind.config(
                bg=KEY_ON if state.get('key_down') else KEY_OFF)
        except Exception:
            pass

        self._root.after(50, self._refresh)
