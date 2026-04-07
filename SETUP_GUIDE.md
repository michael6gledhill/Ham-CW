# Raspberry Pi Morse Code System - Complete Setup Guide

## Overview
This system allows you to send Morse code via iambic paddle through your UV5R radio using a Raspberry Pi with ReSpeaker 2-mic Hat.

---

## Part 1: Wiring Diagram

### Components You Need:
- Raspberry Pi (4B or newer recommended)
- ReSpeaker 2-mic Pi HAT (with 3.5mm speaker output)
- Iambic paddle (with two paddles)
- External 3-position switch
- UV5R radio
- Speaker (connected to ReSpeaker)
- 3.5mm audio cable (ReSpeaker → UV5R microphone input)
- Jumper wires and breadboard (optional)

### Pinout Reference (Raspberry Pi GPIO):
```
GPIO 12: Iambic paddle DIT (or set via config)
GPIO 13: Iambic paddle DAH (or set via config)
GPIO 16: Position 1 (Transmit Mode) - input pin with pull-down
GPIO 19: Position 2 (Off Mode) - input pin with pull-down  
GPIO 20: Position 3 (Speaker Mode) - input pin with pull-down
GPIO 18: PTT Output (Push-To-Talk) - output to UV5R
GPIO 17: Audio output control - output to speaker relay (optional)
```

### Detailed Wiring Steps:

#### Step 1: Iambic Paddle to Raspberry Pi
1. **DIT paddle wire:**
   - Connect one paddle of iambic paddle to GPIO 12 (can be configured)
   - Connect ground to pin 6, 9, 14, 20, 25, 30, 34, or 39 (any GND)

2. **DAH paddle wire:**
   - Connect other paddle to GPIO 13 (can be configured)
   - Connect ground to same ground rail

#### Step 2: External 3-Position Switch Wiring
The switch has 3 positions - wire it like this:

1. **Transmit Position (Position 1):**
   - Switch terminal → GPIO 16 (input)
   - Other terminal → 3.3V or GND (see Step 3 below)

2. **Off Position (Position 2):**
   - Switch terminal (middle) → disconnected or floating

3. **Speaker Mode (Position 3):**
   - Switch terminal → GPIO 20 (input)
   - Other terminal → 3.3V or GND (see Step 3 below)

**Switch Configuration (choose one):**
- **Option A (Pull-down logic):** Each switch position pulls its GPIO HIGH when activated
  - Connect Transmit position switch terminal to 3.3V
  - Connect Speaker mode position switch terminal to 3.3V
  - Connect all GND sides to pin 6 (GND)
  - GPIO pins configured as INPUT with pull-down resistors

- **Option B (Pull-down resistors):** Use 10kΩ pull-down resistors
  - Connect switch terminals to GPIO pins (16, 19, 20)
  - Add 10kΩ resistor from each GPIO to GND
  - Connect switch HIGH side to 3.3V

#### Step 3: UV5R PTT Connection
1. **PTT (Push-To-Talk) Line:**
   - GPIO 18 output → UV5R microphone jack tip (PTT line)
   - GND → UV5R microphone jack sleeve (common ground)
   - Use a relay or transistor if driving direct (recommended for reliability)

2. **Relay Circuit (recommended):**
   - GPIO 18 → Relay control coil (via NPN transistor)
   - Relay normally-open contact → UV5R PTT line
   - Other relay contact → GND

#### Step 4: ReSpeaker Audio Setup
1. **3.5mm audio output from ReSpeaker:**
   - ReSpeaker 3.5mm out → UV5R microphone input (left channel if stereo)
   - Ground connections should be common throughout system

2. **Speaker output:**
   - ReSpeaker speaker output → Your external speaker
   - This is ALSA device `plughw:2,0` or similar (check with `arecord -l`)

---

## Part 2: Installation Steps

### Step 1: Update Raspberry Pi
```bash
sudo apt update
sudo apt upgrade -y
```

### Step 2: Install Required Packages
```bash
# Audio support
sudo apt install -y alsa-utils pulseaudio

# Development tools
sudo apt install -y rustc cargo build-essential libssl-dev pkg-config
```

### Step 3: Set up ReSpeaker Audio Device
```bash
# List audio devices to find ReSpeaker
arecord -l

# Note the card and device numbers. Set ReSpeaker as default if needed.
# Usually it's card 2 for ReSpeaker
```

### Step 4: Install Morse Code Program
```bash
cd ~
git clone <your-repo-url>  # Or download the files
cd morse-code-system

# Build the Rust backend
cargo build --release

# Build will create binary at: target/release/morse-backend
```

### Step 5: Set up Web Frontend
```bash
# The web frontend is static HTML - no build needed!
# Just serve it or open in browser
cd morse-code-system/web
# You can use: python3 -m http.server 8000
# or: npx http-server
```

### Step 6: Create System Service (Optional but Recommended)
```bash
sudo tee /etc/systemd/system/morse-backend.service > /dev/null <<EOF
[Unit]
Description=Morse Code Backend
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/morse-code-system
ExecStart=/home/pi/morse-code-system/target/release/morse-backend
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable morse-backend
sudo systemctl start morse-backend
```

### Step 7: Access the Web Interface
```bash
# Run the backend
./target/release/morse-backend

# In another terminal, serve the frontend
cd web
python3 -m http.server 8000

# Open browser to: http://localhost:8000
# Or from remote: http://<rpi-ip>:8000
```

---

## Part 3: GPIO Pin Reference Table

| Function | GPIO Pin | Mode | Notes |
|----------|----------|------|-------|
| Iambic DIT | 12 (default) | INPUT (pull-down) | Configurable in UI |
| Iambic DAH | 13 (default) | INPUT (pull-down) | Configurable in UI |
| Switch Transmit | 16 (default) | INPUT (pull-down) | Configurable in UI |
| Switch Off | 19 (default) | INPUT (pull-down) | Configurable in UI |
| Switch Speaker | 20 (default) | INPUT (pull-down) | Configurable in UI |
| PTT Output | 18 (default) | OUTPUT | Configurable in UI |
| Audio Relay | 17 (optional) | OUTPUT | For switching speaker input |

---

## Part 4: Configuration File

Create a file `config.toml` in the working directory:

```toml
[gpio]
dit_pin = 12
dah_pin = 13
tx_switch_pin = 16
off_switch_pin = 19
speaker_switch_pin = 20
ptt_pin = 18
audio_relay_pin = 17

[audio]
device = "plughw:2,0"
sample_rate = 44100

[morse]
# Dit duration in milliseconds
dit_duration = 50
```

---

## Troubleshooting

### GPIO Permissions
```bash
# Add your user to gpio group (requires reboot)
sudo usermod -a -G gpio pi
sudo reboot
```

### Audio Device Not Found
```bash
# List all audio devices
arecord -l
aplay -l

# Test audio output
speaker-test -t sine -f 1000 -l 1
```

### ReSpeaker Not Working
```bash
# Install ReSpeaker drivers (if needed)
sudo apt install -y git python3-pip
git clone https://github.com/respeaker/seeed-voicecard.git
cd seeed-voicecard
sudo bash install.sh
sudo reboot
```

### Cannot Access GPIO
```bash
# Ensure you have permissions
groups pi
# Should include 'gpio' group
```

---

## Quick Test Procedures

### Test GPIO Wiring
```bash
# Test iambic paddle DIT (GPIO 12)
gpioget gpiochip0 12

# Should return 0 (LOW) when not pressed, 1 (HIGH) when pressed
```

### Test Audio Output
```bash
# Test speaker output
speaker-test -t sine -f 1000 -l 1

# Test tone generation
sox -n -t alsa plughw:2,0 synth 1 sine 1000
```

### Test PTT Output
```bash
# Before running: Connect LED + 220Ω resistor to GPIO 18 for visual test
# LED should light up when PTT is activated via the switch
```

---

## Safety Reminders

1. **Always ensure UV5R is in VFX mode or test mode before connecting**
2. **Use a relay for PTT output** to protect GPIO from radio backfeed voltage
3. **Test audio levels** - too high can damage radio microphone input
4. **Check local regulations** - some jurisdictions require license for radio use
5. **Keep system grounded** - ensure common ground between all components

---

## Next Steps

1. Follow wiring diagram exactly
2. Connect components one by one, testing each
3. Run through Quick Test Procedures
4. Start the backend and access web interface
5. Configure GPIO pins in the UI
6. Test transmit on low power first
7. Adjust audio levels as needed
