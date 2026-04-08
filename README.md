# Ham-CW

Iambic Mode-B CW keyer for Raspberry Pi Zero W.  Web UI, GPIO speaker,
three SPDT switches, and a TX output pin for keying a radio in text mode.

## Hardware

### GPIO Pins (defaults — all configurable via Settings page)

| Function        | GPIO | Direction |
|-----------------|------|-----------|
| Speaker +       | 20   | Output    |
| Speaker GND     | 21   | Output    |
| DIT Paddle      | 27   | Input     |
| DAH Paddle      | 22   | Input     |
| Mode Switch     | 26   | Input     |
| TX Output       | 16   | Output    |
| Tone Switch Up  | 5    | Input     |
| Tone Switch Down| 6    | Input     |
| WPM Switch Up   | 13   | Input     |
| WPM Switch Down | 19   | Input     |

All inputs use internal pull-ups and are active-low (connect to GND to activate).

### SPDT Switches

Each single-pole double-throw switch has its common terminal wired to **GND**.

- **Mode switch** — one position grounds `pin_mode` (paddle mode); the other
  leaves it floating (text mode).  In paddle mode the iambic paddles key
  directly.  In text mode the Pi grounds `pin_tx` while transmitting CW
  entered from the web UI.
- **Tone switch** — flip up → frequency increases by 50 Hz; flip down →
  decreases.
- **WPM switch** — flip up → speed increases by 1 WPM; flip down → decreases.

### Speaker

Connect a small speaker between `pin_spk` (PWM output) and `pin_spk_gnd`.

### TX Output

`pin_tx` is held HIGH normally and pulled LOW (grounded) when transmitting
in **text mode**.  Wire this to your radio's PTT/key input through
appropriate level shifting if needed.

## Web UI

The keyer serves a web interface on **port 80**.  Open
`http://<pi-ip>/` in any browser on the same network.

- **Transmit page** — shows tone, WPM, mode, paddle indicators, and
  TX status.  In text mode a text box and Send button appear.
- **Settings page** — edit all GPIO pin assignments, tone frequency,
  and WPM speed.  Changes take effect immediately.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/install.sh | bash
```

## Update

```bash
curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/update.sh | bash
```
