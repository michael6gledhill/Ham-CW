# Ham-CW

Iambic Mode-B CW keyer for Raspberry Pi 4 with a 7-inch touchscreen, GPIO PWM sidetone speaker, ALSA sine-wave output to a Baofeng UV-5R, and physical switches for parameter adjustment.

## Features

- **Iambic Mode-B keyer** with adjustable WPM (5-40), frequency (300-1000 Hz), dash weight, and volume
- **Dual audio output**: GPIO PWM square wave to a speaker + clean ALSA sine wave to the 3.5 mm TRRS jack (left channel -> radio mic)
- **5 ms raised-cosine envelope** on the ALSA output for click-free keying
- **Physical switch control**: SPDT Switch A (up/down adjustment), SPDT Switch B (parameter cycle: WPM -> Freq -> Volume)
- **Touchscreen GUI** on the official 7-inch Raspberry Pi display (800x480, dark theme, large touch targets)
- **PTT output** (GPIO pin goes HIGH when keying) for driving a transistor to key the radio
- **Interrupt-driven** switch inputs with software debounce
- **All GPIO pins configurable** from the GUI or config file
- **Auto-start on boot** via systemd
- **Hold both paddles 3 s** to send the Pi's IP address as CW

## Architecture

```
main.py            Application entry point, keyer loop, coordination
config.py          Settings & GPIO pin map, JSON persistence
keyer_engine.py    Iambic Mode-B state machine, Morse table
gpio_handler.py    GPIO setup, edge detection, PWM speaker, PTT
audio_engine.py    ALSA sine-wave output with ring buffer & envelope
gui.py             Tkinter touchscreen GUI
```

## Default GPIO Pinout (BCM)

| Function        | GPIO | Pin | Direction | Notes                            |
|----------------|------|-----|-----------|----------------------------------|
| DIT paddle     | 27   | 13  | Input     | Active-low, internal pull-up     |
| DAH paddle     | 22   | 15  | Input     | Active-low, internal pull-up     |
| Switch A: Up   | 5    | 29  | Input     | SPDT position 1, pull-up         |
| Switch A: Down | 6    | 31  | Input     | SPDT position 2, pull-up         |
| Switch B: Sel  | 13   | 33  | Input     | SPDT, cycles on every flip       |
| Speaker +      | 20   | 38  | Output    | PWM square wave sidetone         |
| Speaker -      | 21   | 40  | Output    | Held LOW (ground reference)      |
| PTT output     | 16   | 36  | Output    | HIGH when keying                 |

All pins are editable from the touchscreen GUI or `~/.ham-cw.conf`.

## Wiring

### Iambic Paddles

- DIT contact -> GPIO 27 (pin 13)
- DAH contact -> GPIO 22 (pin 15)
- Common (ground) -> any GND pin (e.g. pin 14)

Internal pull-up resistors are enabled.  Pressing a paddle pulls the pin LOW.

### Parameter Switches

**Switch A (Up/Down adjustment)** - SPDT toggle:
- Common -> GND
- Throw 1 (Up) -> GPIO 5 (pin 29)
- Throw 2 (Down) -> GPIO 6 (pin 31)

Each flip increments or decrements the currently selected parameter by one step (WPM +/-1, Freq +/-50 Hz, Volume +/-5%).

**Switch B (Parameter select)** - SPDT toggle:
- Common -> GND
- Either throw -> GPIO 13 (pin 33)

Every flip (either direction) cycles through: **WPM -> Frequency -> Volume -> WPM...**

### Speaker (Sidetone)

Connect a small speaker or piezo buzzer directly:
- Speaker + -> GPIO 20 (pin 38)
- Speaker - -> GPIO 21 (pin 40)

GPIO 21 is held LOW as a ground reference.  GPIO 20 drives a PWM square wave.  For speakers > ~50 mA, use a driver transistor.

### TRRS Audio to Baofeng UV-5R

The Pi 4's 3.5 mm TRRS jack outputs a clean sine wave on the **left channel (Tip)**.

TRRS wiring to Baofeng 2.5 mm mic plug:

| Pi TRRS     | Signal       | Baofeng 2.5mm |
|-------------|-------------|---------------|
| Tip         | Left audio  | Tip (Mic)     |
| Ring 2      | Ground      | Ring (GND)    |

A voltage divider may be needed to reduce the Pi's line-level output to mic level:

```
Pi Tip ---[10k]---+----> Baofeng Mic Tip
                  |
                [1k]
                  |
                 GND
```

### PTT

PTT is controlled by a **manual SPDT switch** wired directly between the radio's PTT line and ground.  The keyer does not control PTT.

The GPIO PTT output (pin 16) is available for future use with a transistor driver:

```
GPIO 16 ---[1k]--- Base (2N2222)
                    Emitter -> GND
                    Collector -> Radio PTT line
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/install.sh | bash
```

This installs dependencies (`python3-rpi.gpio`, `python3-alsaaudio`, `python3-tk`), clones the repo, and enables the systemd service.

### Audio Output Configuration

Ensure the Pi's audio output is set to the 3.5 mm headphone jack:

```bash
sudo raspi-config
# Advanced Options -> Audio -> Force 3.5mm
```

Or via ALSA:
```bash
amixer cset numid=3 1    # 1 = headphone jack
```

## Update

```bash
curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/update.sh | bash
```

## Usage

The GUI appears automatically on the 7-inch touchscreen after boot.

- **Tap a parameter row** to select it (or flip Switch B)
- **Tap +/-** or flip Switch A to adjust the selected parameter
- **Test Tone** sends a 0.5 s tone through both speaker and ALSA
- **Send** plays entered text as Morse code
- **Hold both paddles 3 s** to hear the Pi's IP address in CW
- **Pressing a paddle** during text playback cancels the send

Without a display, the keyer runs headless (GPIO + audio only).

## Service Management

```bash
sudo systemctl status ham-cw
sudo systemctl restart ham-cw
sudo journalctl -u ham-cw -f
```

## Morse Timing Reference

Using the PARIS standard (50 dit-units per word):

| WPM | Dit (ms) | Dah (ms) | Char gap (ms) | Word gap (ms) |
|-----|----------|----------|---------------|---------------|
| 10  | 120      | 360      | 360           | 840           |
| 15  | 80       | 240      | 240           | 560           |
| 20  | 60       | 180      | 180           | 420           |
| 25  | 48       | 144      | 144           | 336           |
| 30  | 40       | 120      | 120           | 280           |
| 40  | 30       | 90       | 90            | 210           |
