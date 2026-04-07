# Ham-CW

## Connecting the Pi 4 Audio Jack to a Baofeng UV-5R

The Raspberry Pi 4 has a 3.5 mm TRRS jack. The keyer outputs a clean sine wave on the **left audio channel (Tip)** which feeds the Baofeng's microphone input.

### Pi 4 TRRS Pinout

```
        Tip    = Left audio  (tone output)
        Ring 1 = Right audio (unused)
        Ring 2 = Ground
        Sleeve = Composite video (unused)
```

### Baofeng UV-5R Mic/Speaker Connector

The Baofeng uses a Kenwood-style dual-pin connector:

- **2.5 mm plug** = Mic + PTT
- **3.5 mm plug** = Speaker/Ear (not used here)

On the **2.5 mm mic plug**:

```
        Tip    = Microphone input
        Ring   = PTT (short to ground = transmit)
        Sleeve = Ground
```

### Wiring

Connect only two wires from the Pi TRRS to the Baofeng 2.5 mm plug:

```
Pi TRRS Tip (Left audio) ---[10k]---+---> Baofeng 2.5mm Tip (Mic)
                                    |
                                  [1k]
                                    |
Pi TRRS Ring 2 (Ground) ------------+---> Baofeng 2.5mm Sleeve (GND)
```

The 10k/1k voltage divider reduces the Pi's line-level output (~1 V peak) to mic level (~90 mV peak). Without it the radio will be overdriven and distorted.

### PTT

PTT is handled by a **manual SPDT switch** wired between the Baofeng 2.5 mm Ring (PTT) and Ground. Flip the switch to transmit, flip back to receive.

### Audio Output Setup

Make sure the Pi is sending audio out the 3.5 mm jack (not HDMI):

```bash
sudo raspi-config
# Advanced Options -> Audio -> Force 3.5mm ('Headphones')
```

The **Volume** setting in the keyer controls the ALSA output level to the radio. The GPIO sidetone speaker always plays at a fixed volume.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/install.sh | bash
```

## Update

```bash
curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/update.sh | bash
```
