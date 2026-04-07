#!/usr/bin/env bash
# ham-cw install script for Raspberry Pi (Raspberry Pi OS)
# Run once as the pi user: bash install.sh

set -e

echo "=== ham-cw installer ==="

# 1. System packages ----------------------------------------------------------
echo "Updating package list..."
sudo apt-get update -qq

echo "Installing dependencies..."
sudo apt-get install -y --no-install-recommends \
    python3-alsaaudio \
    espeak \
    git

# 2. GPIO group ---------------------------------------------------------------
if ! groups "$USER" | grep -q gpio; then
    echo "Adding $USER to gpio group..."
    sudo usermod -a -G gpio "$USER"
    echo "NOTE: Log out and back in (or reboot) for group change to take effect."
fi

# 3. ALSA config --------------------------------------------------------------
cd "$(dirname "$0")"
if [ -f asoundrc ]; then
    echo "Installing ~/.asoundrc (ALSA dmix for ReSpeaker HAT)..."
    cp asoundrc "$HOME/.asoundrc"
fi

# 4. Systemd service -----------------------------------------------------------
if [ -f ham-cw.service ]; then
    echo "Installing systemd service..."
    sudo cp ham-cw.service /etc/systemd/system/ham-cw.service
    sudo systemctl daemon-reload
    sudo systemctl enable ham-cw
fi

echo ""
echo "Install complete."
echo ""
echo "=== Quick start ==="
echo "  python3 ham_cw.py           # 20 WPM (default)"
echo "  python3 ham_cw.py 25        # 25 WPM"
echo "  sudo systemctl start ham-cw # run as service"
echo ""
echo "Web UI: http://$(hostname -I | awk '{print $1}'):8080"
echo "  GPIO 18 (pin 12)  PTT output to radio"
echo ""
echo "To autostart on boot, run:"
echo "  sudo cp ham-cw.service /etc/systemd/system/"
echo "  sudo systemctl enable --now ham-cw"
