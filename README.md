# Ham-CW

Iambic CW keyer for Raspberry Pi Zero W with GPIO sidetone speaker, SPDT TX/RX switch, iambic paddles, and PTT output for radio.

## Features

- Iambic Mode-B keyer with adjustable WPM (5-60), frequency (200-2000 Hz), and dash weight
- GPIO PWM sidetone through a speaker connected directly to GPIO pins
- SPDT switch for TX/RX mode selection
- PTT output (active HIGH) for radio transmit via transistor
- Web UI on port 8080 for settings, test tone, paddle monitor, and sending CW text
- All GPIO pins configurable from the web UI
- Config saved to `~/.ham-cw.conf`
- Hold both paddles 3 seconds to send IP address as CW

## Default GPIO Pinout (BCM)

| Function     | GPIO | Direction | Notes                        |
|-------------|------|-----------|------------------------------|
| DIT paddle  | 27   | Input     | Active-low, internal pull-up |
| DAH paddle  | 22   | Input     | Active-low, internal pull-up |
| TX switch   | 5    | Input     | SPDT position 1, pull-up     |
| RX switch   | 6    | Input     | SPDT position 2, pull-up     |
| Speaker +   | 20   | Output    | PWM square wave sidetone     |
| Speaker -   | 21   | Output    | Held LOW (ground reference)  |
| PTT output  | 16   | Output    | HIGH when keying in TX mode  |

All pin assignments are editable via the web UI.

## Wiring

### Iambic Paddles

Connect your paddles to the Pi's GPIO header:

- DIT contact -> GPIO 27 (pin 13)
- DAH contact -> GPIO 22 (pin 15)
- Common (ground) -> any GND pin (e.g. pin 14)

The inputs use internal pull-up resistors. Pressing a paddle pulls the pin LOW.

### SPDT TX/RX Switch

A single-pole double-throw switch selects TX or RX mode:

- Common terminal -> GND
- Position 1 (TX) -> GPIO 5 (pin 29)
- Position 2 (RX) -> GPIO 6 (pin 31)

Paddles and PTT only operate when the switch is in the TX position.

### Speaker

Connect a small speaker (8 ohm or piezo buzzer) directly between two GPIO pins:

- Speaker + -> GPIO 20 (pin 38)
- Speaker - -> GPIO 21 (pin 40)

GPIO 21 is held LOW as a ground reference. GPIO 20 drives a PWM square wave at the configured frequency. Volume is controlled by varying the PWM duty cycle.

### PTT Output (for Baofeng UV-5R or similar)

GPIO 16 goes HIGH when keying in TX mode. Use a transistor to switch the radio's PTT line:

```
GPIO 16 ---[1k]---+--- Base (2N2222)
                   |
                  Emitter -> GND
                   |
                  Collector -> Radio PTT line (2.5mm tip)
```

The radio's PTT expects a short to ground to transmit.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/install.sh | bash
```

## Update

```bash
curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/update.sh | bash
```

## Web UI

Open `http://<pi-ip>:8080` in a browser to adjust settings, test the sidetone, monitor paddles, and send CW text.

## Service Management

```bash
sudo systemctl status ham-cw
sudo systemctl restart ham-cw
sudo journalctl -u ham-cw -f
```
