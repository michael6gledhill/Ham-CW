# 📋 COMPLETE INSTALLATION CHECKLIST

Follow these steps in order. Check off each when complete.

---

## PHASE 1: PREPARATION (15 minutes)

### Get Your Files
- [ ] Download/clone all source files
- [ ] Verify you have:
  - [ ] Cargo.toml
  - [ ] src/main.rs
  - [ ] web/index.html
  - [ ] README.md, SETUP_GUIDE.md, WIRING_REFERENCE.md
  - [ ] install.sh

### Set Up Directory Structure
```bash
mkdir -p ~/morse-code-system/src ~/morse-code-system/web
cd ~/morse-code-system
# Place files in appropriate locations
```

- [ ] Cargo.toml in root
- [ ] src/main.rs in src/ folder
- [ ] web/index.html in web/ folder
- [ ] All .md files in root
- [ ] install.sh in root

### Make Script Executable
```bash
chmod +x install.sh
```

- [ ] install.sh is executable

---

## PHASE 2: SOFTWARE INSTALLATION (20 minutes)

### Run Installation Script
```bash
bash install.sh
```

This will:
- [ ] Update system packages
- [ ] Install Rust compiler
- [ ] Install GPIO libraries
- [ ] Install audio tools
- [ ] Add you to gpio group

### Build Backend
```bash
cargo build --release
```

Wait for compilation to complete. This takes 2-5 minutes.

- [ ] Compilation successful
- [ ] Binary at: ./target/release/morse-backend (check with `ls`)
- [ ] Binary size ~30-50MB (normal!)

### Test Backend Runs
```bash
./target/release/morse-backend
```

Expected output:
```
🔧 Morse Code System - Rust Backend
Starting on 0.0.0.0:3030
```

- [ ] Backend starts without errors
- [ ] Backend listening on port 3030
- [ ] Can see "Starting on 0.0.0.0:3030"

Press Ctrl+C to stop for now.

---

## PHASE 3: WIRING YOUR HARDWARE (45 minutes)

### Read Wiring Guide
```bash
cat WIRING_REFERENCE.md
```

- [ ] Understand GPIO pinout
- [ ] Know which pins you're using
- [ ] Have all 3 documents open while wiring

### Gather Components
- [ ] Raspberry Pi (powered, ready to use)
- [ ] Breadboard or wiring setup
- [ ] Iambic paddle
- [ ] 3-position switch
- [ ] Jumper wires (several)
- [ ] 10kΩ resistors (3 recommended)
- [ ] Optional: relay, transistor, LED for testing

### Wire Iambic Paddle
Follow WIRING_REFERENCE.md section "Iambic Paddle"

- [ ] DIT paddle → GPIO 12 (Pin 32)
- [ ] DAH paddle → GPIO 13 (Pin 33)
- [ ] Both grounds → Pin 6 (GND)
- [ ] Double-check with ohmmeter (continuity test)

### Wire 3-Position Switch
Follow WIRING_REFERENCE.md section "Three-Position Switch"

**Position 1 (TX):**
- [ ] Switch terminal → 10kΩ resistor → GPIO 16 (Pin 36)
- [ ] Other side of resistor → Pin 6 (GND)

**Position 2 (OFF):**
- [ ] Middle terminal → floating (no connection)

**Position 3 (Speaker):**
- [ ] Switch terminal → 10kΩ resistor → GPIO 20 (Pin 38)
- [ ] Other side of resistor → Pin 6 (GND)

**Switch 3.3V side (if using pull-up):**
- [ ] Switch 3.3V wire → Pin 1 (3.3V)

### Wire PTT Output
Follow WIRING_REFERENCE.md section "UV5R Connections"

- [ ] GPIO 18 (Pin 12) → Relay coil (via transistor if using relay)
- [ ] Relay NO contact → UV5R PTT line
- [ ] Relay coil ground → Pin 6 (GND)

### Audio Connections
- [ ] ReSpeaker 3.5mm output → UV5R microphone input
- [ ] ReSpeaker speaker output → External speaker
- [ ] All grounds tied together at Pin 6

### Verification
- [ ] All connections are snug
- [ ] No loose wires
- [ ] No shorts between pins
- [ ] All ground connections to same point (Pin 6)

---

## PHASE 4: GPIO TESTING (15 minutes)

### Test Paddle Inputs
```bash
# Test DIT (GPIO 12)
gpioget gpiochip0 12
# Should return 0 when not pressed
# Press DIT paddle → should return 1

# Test DAH (GPIO 13)
gpioget gpiochip0 13
# Same behavior as DIT
```

- [ ] DIT returns 0 when released
- [ ] DIT returns 1 when pressed
- [ ] DAH returns 0 when released
- [ ] DAH returns 1 when pressed

### Test Switch Position (TX)
```bash
gpioget gpiochip0 16
# Should return 0 in other positions
# Should return 1 when in TX position
```

- [ ] Returns 0 in OFF position
- [ ] Returns 1 in TX position
- [ ] Returns 0 in Speaker position

### Test Switch Position (Speaker)
```bash
gpioget gpiochip0 20
# Should return 0 in other positions
# Should return 1 when in Speaker position
```

- [ ] Returns 0 in TX position
- [ ] Returns 1 in Speaker position
- [ ] Returns 0 in OFF position

### Test PTT Output
**Before test:** Connect LED + 220Ω resistor to GPIO 18 for visual feedback

```bash
# Turn on (LED should light)
gpioset gpiochip0 18=1

# Turn off (LED should turn off)
gpioset gpiochip0 18=0
```

- [ ] LED lights on `gpioset 18=1`
- [ ] LED turns off on `gpioset 18=0`
- [ ] No LED? Multimeter shows voltage difference?

---

## PHASE 5: AUDIO SETUP (10 minutes)

### Find ReSpeaker Device
```bash
arecord -l
```

Look for output mentioning "seeed" or "respeaker"

```bash
aplay -l
```

Find the playback device for ReSpeaker

- [ ] ReSpeaker device identified
- [ ] Device number noted (usually card 2)

### Test Audio Output
```bash
# Test beep sound
speaker-test -t sine -f 1000 -l 1
```

Should hear 1000Hz tone through speaker

- [ ] Audio plays through ReSpeaker speaker
- [ ] Volume is adjustable

---

## PHASE 6: SYSTEM STARTUP (5 minutes)

### Terminal 1: Start Backend
```bash
cd ~/morse-code-system
./target/release/morse-backend
```

Expected:
```
🔧 Morse Code System - Rust Backend
Starting on 0.0.0.0:3030
```

- [ ] Backend started successfully
- [ ] Listening on 0.0.0.0:3030

### Terminal 2: Start Web Server
```bash
cd ~/morse-code-system/web
python3 -m http.server 8000
```

Expected:
```
Serving HTTP on 0.0.0.0 port 8000
```

- [ ] Web server started
- [ ] Listening on port 8000

### Terminal 3 (or browser): Open Web Interface
```bash
# From same Raspberry Pi:
# Open browser to: http://localhost:8000

# OR from remote computer on same network:
# Open browser to: http://<rpi-ip>:8000
```

You should see the Morse Code System interface with:
- [ ] GPIO Configuration section
- [ ] System Status section
- [ ] Send Morse Code section
- [ ] Event Log at bottom

---

## PHASE 7: CONFIGURATION & TESTING (10 minutes)

### Configure GPIO Pins
In web interface:

- [ ] DIT Pin: Set to 12
- [ ] DAH Pin: Set to 13
- [ ] TX Switch: Set to 16
- [ ] Speaker Switch: Set to 20
- [ ] PTT Output: Set to 18
- [ ] DIT Duration: Keep at 50ms

Click "💾 Save Configuration"

- [ ] Configuration saved
- [ ] No errors shown

### Load Status
Click "🔄 Refresh Status"

- [ ] Status shows all your GPIO pins
- [ ] Last Code shows "NONE" or previous code

### Send Test Morse
In "Send Morse Code" field, enter:
```
... --- ...
```

Click "📤 Send Code"

Expected:
- [ ] Morse code appears in log
- [ ] Status updates "Last Code"
- [ ] PTT activates (LED on GPIO 18 flashes if you set it up)
- [ ] No errors in browser console (F12)

### Check Event Log
Scroll to bottom

- [ ] "Waiting for events..." message gone
- [ ] New entries showing your actions
- [ ] Timestamps visible
- [ ] Format: [YYYY-MM-DD HH:MM:SS] EVENT

---

## PHASE 8: REAL TRANSMISSION TEST (5 minutes)

### Prepare Radio
- [ ] UV5R powered on
- [ ] Set to appropriate frequency for testing
- [ ] Volume set to reasonable level
- [ ] **IMPORTANT: Start on low power!**

### Test PTT Activation
1. Open web interface
2. Move 3-position switch to TX position
3. Press paddle or send morse via web
4. Verify:
   - [ ] UV5R transmits (PTT LED lights)
   - [ ] Audio is routed correctly
   - [ ] PTT releases after transmission
   - [ ] No stuck TX

### Test Speaker Routing (Optional)
1. Move switch to Speaker position
2. Key the radio externally (another radio or signal generator)
3. Verify:
   - [ ] Audio from UV5R plays through Raspberry Pi speaker
   - [ ] Audio is clear and audible

### Test OFF Position
1. Move switch to OFF position
2. Press paddle
3. Verify:
   - [ ] UV5R does NOT transmit
   - [ ] No audio output

---

## PHASE 9: PRODUCTION SETUP (Optional but Recommended)

### Create System Service
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

- [ ] Service file created
- [ ] Service enabled to start on boot
- [ ] Backend running as service

### Verify Auto-Start (Optional)
```bash
sudo reboot
# After reboot:
pgrep morse-backend
# Should show process ID if running
```

- [ ] Backend starts automatically after reboot
- [ ] Web interface accessible immediately

---

## PHASE 10: FINAL CHECKS ✅

### System Stability
- [ ] Run for 30+ minutes without issues
- [ ] No crashes or errors
- [ ] Web interface responsive
- [ ] GPIO inputs working reliably

### Documentation
- [ ] You understand the wiring
- [ ] You know where GPIO pins are
- [ ] You've read SETUP_GUIDE.md
- [ ] You know how to access logs

### Emergency Procedures
- [ ] You know how to stop backend (Ctrl+C)
- [ ] You know how to restart system
- [ ] You know how to check logs (`tail -f morse.log`)

---

## 🎉 CONGRATULATIONS!

You have successfully:
- ✅ Installed Rust backend
- ✅ Built web interface
- ✅ Wired all components
- ✅ Tested GPIO inputs/outputs
- ✅ Verified audio routing
- ✅ Sent first morse code
- ✅ Transmitted on UV5R

---

## NEXT STEPS

1. **Log sessions** for future reference
2. **Adjust DIT duration** if needed in web interface
3. **Fine-tune audio levels** with UV5R mic gain
4. **Create custom morse messages** in web interface
5. **Share your success!** 📡

---

## QUICK REFERENCE

| Task | Command |
|------|---------|
| Start backend | `./target/release/morse-backend` |
| Start web | `cd web && python3 -m http.server 8000` |
| View logs | `tail -f morse.log` |
| Test DIT | `gpioget gpiochip0 12` |
| Test TX switch | `gpioget gpiochip0 16` |
| Test PTT | `gpioset gpiochip0 18=1` |
| Rebuild | `cargo build --release` |
| Access web | `http://localhost:8000` |

---

**Happy Morse Coding! 📡✨**

If issues arise, see SETUP_GUIDE.md Troubleshooting section.
