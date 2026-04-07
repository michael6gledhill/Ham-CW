# Quick Wiring Reference

## Physical Component Layout

```
RASPBERRY PI GPIO HEADER (40-pin)
=================================

Top Row (Pins 1-20):              Bottom Row (Pins 21-40):
1   3.3V                          21  GND
2   5V                            22  GPIO 25
3   GPIO 2 (SDA)                  23  GPIO 11 (SPI CLK)
4   5V                            24  GPIO 8 (SPI CE0)
5   GPIO 3 (SCL)                  25  GND
6   GND                           26  GPIO 7 (SPI CE1)
7   GPIO 4                        27  GPIO 0 (EEPROM ID_SD)
8   GPIO 14 (UART TX)             28  GPIO 1 (EEPROM ID_SC)
9   GND                           29  GPIO 5
10  GPIO 15 (UART RX)             30  GND
11  GPIO 17 ⭐ AUDIO RELAY        31  GPIO 6
12  GPIO 18 ⭐ PTT OUTPUT         32  GPIO 12 ⭐ DIT PADDLE
13  GPIO 27                       33  GPIO 13 ⭐ DAH PADDLE
14  GND                           34  GND     ⭐ OFF SWITCH
15  GPIO 22                       35  GPIO 19 
16  GPIO 23                       36  GPIO 16 ⭐ TX SWITCH
17  3.3V                          37  GPIO 26
18  GPIO 24                       38  GPIO 20 ⭐ SPEAKER SWITCH
19  GPIO 10 (SPI MOSI)            39  GND
20  GND                           40  GPIO 21
```

## Essential Connections

### Ground Points (Pick Any):
- Pin 6, 9, 14, 20, 25, 30, 34, 39

### 3.3V Power Points:
- Pin 1, 17

### Recommended Pins Used in This System:
```
GPIO 12  ← DIT Paddle
GPIO 13  ← DAH Paddle
GPIO 16  ← TX Switch (Position 1)
GPIO 19  ← OFF Switch (Position 2)
GPIO 20  ← Speaker Switch (Position 3)
GPIO 18  → PTT Output to UV5R
GPIO 17  → (Optional) Speaker relay control
```

## Step-by-Step Wiring Checklist

### Part 1: Iambic Paddle (2 wires)
- [ ] DIT paddle to GPIO 12
- [ ] DAH paddle to GPIO 13
- [ ] Both paddles ground to pin 6 (or any GND)

### Part 2: Three-Position Switch (3 switch terminals + ground)
- [ ] Transmit terminal (Pos 1) to GPIO 16 via 10kΩ resistor to GND
- [ ] OFF terminal (Pos 2) → floating (no connection)
- [ ] Speaker terminal (Pos 3) to GPIO 20 via 10kΩ resistor to GND
- [ ] Switch common ground to pin 6 (or any GND)

### Part 3: PTT Output (2 wires)
- [ ] GPIO 18 to relay coil (via NPN transistor 2N2222 or similar)
- [ ] Relay NO contact to UV5R PTT line
- [ ] Relay other contact to GND (pin 6)

### Part 4: Audio Connections
- [ ] ReSpeaker 3.5mm output to UV5R microphone input
- [ ] ReSpeaker speaker output connected to external speaker
- [ ] Audio grounds tied to main system ground

### Part 5: Optional Components
- [ ] GPIO 17 through relay to switch speaker input source
- [ ] LED + 220Ω resistor on GPIO 18 for PTT indicator

## Common GPIO Modes

```
INPUT (Reading from paddle/switch):
- GPIO 12, 13, 16, 19, 20
- Pull-down resistor (10kΩ to GND) recommended

OUTPUT (Controlling radio):
- GPIO 18 (PTT)
- GPIO 17 (Speaker relay) - optional
```

## Testing Each Component

### Test DIT Paddle:
```bash
gpioget gpiochip0 12
# Press DIT: should show 1
# Release: should show 0
```

### Test Switch Position 1 (TX):
```bash
gpioget gpiochip0 16
# Switch to TX pos: should show 1
# Switch to other: should show 0
```

### Test PTT Output:
```bash
# Before: Connect LED + 220Ω resistor to GPIO 18
gpioset gpiochip0 18=1  # LED should light
gpioset gpiochip0 18=0  # LED should turn off
```

### Test Audio:
```bash
# List audio devices
arecord -l
aplay -l

# Test speaker output
speaker-test -t sine -f 1000 -l 1
```

## UV5R Connections

### Microphone Jack (3.5mm):
```
TIP      → ReSpeaker audio output
RING     → PTT signal from relay
SLEEVE   → Ground (common with Raspberry Pi)
```

OR if using standard mic jack with separate PTT:

```
Audio     → ReSpeaker out
PTT line  → GPIO 18 (via relay)
Ground    → Common ground
```

## ReSpeaker Audio Device Discovery

```bash
# Find ReSpeaker device number
arecord -l

# Usually appears as:
# card 2: seeed2micvoicec [seeed-2mic-voicecard], device 0: ...

# Use: plughw:2,0
```

## Troubleshooting Quick Fixes

### GPIO Permission Denied:
```bash
sudo usermod -a -G gpio pi
sudo reboot
```

### Audio Device Not Found:
```bash
# Reinstall ReSpeaker drivers
git clone https://github.com/respeaker/seeed-voicecard.git
cd seeed-voicecard
sudo bash install.sh
sudo reboot
```

### PTT Not Working:
1. Check GPIO 18 with LED first
2. Verify relay coil voltage (usually 5V or 12V)
3. Test with multimeter if available
4. Check UV5R PTT line for shorts

### Switch Not Registering:
1. Verify GPIO pins with `gpioget gpiochip0 PIN`
2. Check for loose connections
3. Test with LED first
4. Verify pull-down resistors installed
