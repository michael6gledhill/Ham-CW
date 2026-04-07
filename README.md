# Ham-CW

Iambic CW keyer for Raspberry Pi Zero + ReSpeaker 2-Mic HAT + Baofeng UV-5R.

Paddles generate sidetone through the ReSpeaker HAT and key the radio via PTT.

## What you need

| Item | Notes |
|------|-------|
| Raspberry Pi Zero (W or 2 W) | Any Pi works, Zero is smallest |
| ReSpeaker 2-Mic Pi HAT | Stacks on the GPIO header |
| Iambic paddle | Common-ground type (both paddles share one ground wire) |
| Baofeng UV-5R | Or any radio with Kenwood 2-pin connector |
| 2.5mm TRS plug | For the Baofeng mic/PTT jack |
| 2N2222 NPN transistor | For PTT switching (or any small NPN/N-FET) |
| 1k resistor | Transistor base resistor |
| 100k resistor | Audio attenuator (speaker amp to mic level) |
| 1k resistor | Audio attenuator ground leg |
| 0.1uF capacitor | DC blocking cap for audio line (optional but recommended) |
| SPDT toggle switch (x2) | TX/RX mode switches |
| Small speaker (8 ohm) | For initial testing |
| Headphones (3.5mm) | For monitoring sidetone |
| Hook-up wire, solder, etc. | |

## Audio plan

The ReSpeaker 2-Mic HAT has two audio outputs:

```
                          +------------------+
                          |  ReSpeaker HAT   |
                          |                  |
   Headphones  <----------| 3.5mm jack       |  You hear sidetone here
                          |                  |
   To Baofeng mic  <------| 2-pin speaker    |  CW tone goes to radio here
                          |  connector       |
                          +------------------+
```

- **Headphone jack** - plug in headphones to hear the sidetone while operating
- **Speaker connector (JST 2-pin)** - feeds the CW tone into the Baofeng's
  microphone input through a voltage divider

Both outputs play the same audio from the WM8960 codec, so you hear what you
send.

## Step 1 - Test the speaker connector

Before wiring anything to the radio, verify the 2-pin speaker output works.

### Wiring

The JST 2-pin connector on the ReSpeaker HAT is labeled **SPK**. It has two
pins: **SPK+** and **SPK-**.

```
ReSpeaker HAT
  SPK+ ---------> Speaker + (red wire)
  SPK- ---------> Speaker - (black wire)
```

Connect any small 4-8 ohm speaker to the two pins. Polarity doesn't matter
for testing.

### Test

```bash
# Install and start
cd ~/Ham-CW
bash install.sh
sudo systemctl start ham-cw
```

Open the web UI at `http://<pi-ip>:8080`, hit **Test tone**, and you should
hear a dit-dah through the speaker. Adjust volume with the slider.

If you plug headphones into the 3.5mm jack at the same time, you should hear
the tone in both the speaker and the headphones.

## Step 2 - Wire the GPIO

### Raspberry Pi GPIO header (active-low inputs, accent on BCM numbering)

All inputs use internal pull-up resistors. Connect one side of each
switch/paddle to the GPIO pin, the other side to **ground** (any GND pin).

```
Pi GPIO header (active-low, accent on BCM pin numbers)
+-------+------+---------------------------+
| BCM   | Pin# | Function                  |
+-------+------+---------------------------+
| GND   |  6   | Common ground for all     |
| GPIO 5|  29  | DIT paddle                |
| GPIO 6|  31  | DAH paddle                |
| GPIO 13|  33 | TX switch (ground = TX)   |
| GPIO 16|  36 | RX switch (ground = RX)   |
| GPIO 18|  12 | PTT output (HIGH = key)   |
+-------+------+---------------------------+
```

**Pins to avoid** (used by the ReSpeaker HAT):
GPIO 2, 3 (I2C), 17 (button), 18-21 (I2S audio)

> **Note:** GPIO 18 is used by I2S on the ReSpeaker HAT. If PTT doesn't work
> on GPIO 18, change it to GPIO 22 or 23 via the web UI.

### Paddle wiring

```
Iambic Paddle
  Common (ground) -----> Pi GND (pin 6, 9, 14, 20, 25, 30, 34, or 39)
  DIT contact ----------> Pi GPIO 5 (pin 29)
  DAH contact ----------> Pi GPIO 6 (pin 31)
```

### TX/RX switches

Two toggle switches. Each has one terminal to the GPIO pin, the other to
ground. When the switch is closed (grounded), that mode is active.

```
TX switch:  one side -> GPIO 13 (pin 33),  other side -> GND
RX switch:  one side -> GPIO 16 (pin 36),  other side -> GND
```

Paddles only produce sidetone and key PTT when the TX switch is in the
grounded (TX) position.

## Step 3 - Wire the Baofeng UV-5R

The UV-5R has a Kenwood-style 2-pin connector:
- **2.5mm jack** = microphone input + PTT
- **3.5mm jack** = earpiece/speaker output

### PTT circuit

GPIO 18 drives an NPN transistor that grounds the PTT line when keying.

```
                    1k
Pi GPIO 18 ---[resistor]---+
                           |
                      B  |/
                   2N2222 |    C = Collector
                         \|    E = Emitter
                           |
          Baofeng PTT -----+--- C (collector)
          (2.5mm tip)      
                           E (emitter)
                           |
                          GND --- Baofeng GND (2.5mm sleeve)
                                  and Pi GND
```

When GPIO 18 goes HIGH, the transistor turns on, pulling PTT to ground,
which keys the radio.

### Audio circuit

The ReSpeaker speaker amp outputs a hot signal (~1-3V peak). The Baofeng mic
input expects millivolts. Use a voltage divider to attenuate ~100:1.

```
ReSpeaker SPK+ ---[100k]---+--- 0.1uF cap ---+--- Baofeng mic
                            |                  |   (2.5mm ring)
                          [1k]                 |
                            |                  |
ReSpeaker SPK- ------------+------------------+--- Baofeng GND
                                                   (2.5mm sleeve)
```

The 100k/1k divider cuts the signal to about 1/100th. The cap blocks DC.

### 2.5mm plug pinout (Baofeng mic jack)

```
        Tip  = PTT (ground to transmit)
        Ring = Microphone input
        Sleeve = Ground
```

### Complete wiring summary

```
ReSpeaker SPK+ --[100k]--+-[0.1uF cap]--> 2.5mm ring (mic)
ReSpeaker SPK- ----------+--------------> 2.5mm sleeve (GND)
Pi GPIO 18 ----[1k]---B 2N2222 C---------> 2.5mm tip (PTT)
                           E
                           |
                          GND (shared with Pi and radio)
Pi GND ----------------------------------------> 2.5mm sleeve
```

## Step 4 - Listen to the radio

Plug headphones or an external speaker into the **Baofeng 3.5mm jack**
(earpiece output) to hear incoming signals.

The ReSpeaker 3.5mm headphone jack plays the sidetone so you can hear your
own sending. You'll have:
- **ReSpeaker headphones** = your sidetone (what you're sending)
- **Baofeng earpiece** = what the radio hears (other stations)

## Software setup

```bash
# First time
git clone https://github.com/michael6gledhill/Ham-CW.git ~/Ham-CW
cd ~/Ham-CW
bash install.sh

# Update anytime
bash ~/Ham-CW/update.sh
```

## Web UI

Open `http://<pi-ip>:8080` to adjust:
- **WPM** (5-60)
- **Tone frequency** (200-2000 Hz)
- **Dash weight** (2.0x - 5.0x dit length)
- **Volume** (0-100%)
- **GPIO pin assignments** (DIT, DAH, TX, RX, PTT)
- **Test tone** button
- **Paddle monitor** (live LED indicators)
- **Send CW** (type text, sends as Morse)

## Tips

- Hold both paddles for 3 seconds to hear the Pi announce its IP address
- All pin assignments are configurable in the web UI and saved to
  `~/.ham-cw.conf`
- The sidetone plays through both the speaker connector and headphone jack
  simultaneously
- Start with low volume when first connecting to the radio, then increase
  until the signal is clean
- Set the Baofeng to a simplex frequency, narrow band (12.5 kHz), low power
