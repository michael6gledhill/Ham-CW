#!/usr/bin/env bash
# ham-cw install script for Raspberry Pi
# curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/install.sh | bash

set -euo pipefail

REPO_URL="https://github.com/michael6gledhill/Ham-CW.git"
INSTALL_DIR="${HAM_CW_DIR:-$HOME/Ham-CW}"
SERVICE="ham-cw"

echo "=== ham-cw installer ==="

# 1. System packages
echo "[ham-cw] installing dependencies..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3-pigpio pigpio \
    python3-gpiozero \
    python3-flask \
    python3-numpy \
    python3-alsaaudio \
    portaudio19-dev \
    git

# 2. Install pyaudio via pip (not always in apt)
if ! python3 -c 'import pyaudio' 2>/dev/null; then
    echo "[ham-cw] installing pyaudio via pip..."
    pip3 install --break-system-packages pyaudio 2>/dev/null || \
    pip3 install pyaudio 2>/dev/null || \
    echo "[ham-cw] pyaudio not available, will use ALSA fallback"
fi

# 3. Enable pigpio daemon (DMA-timed PWM)
echo "[ham-cw] enabling pigpio daemon..."
sudo systemctl enable pigpiod
sudo systemctl start pigpiod

# 4. GPIO group
if ! groups "$USER" | grep -q gpio; then
    echo "[ham-cw] adding $USER to gpio group..."
    sudo usermod -a -G gpio "$USER"
fi

# 5. Clone or pull repo
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "[ham-cw] pulling latest code..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "[ham-cw] cloning repo to $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 6. Systemd service
echo "[ham-cw] installing systemd service..."
sudo cp "$INSTALL_DIR/ham-cw.service" /etc/systemd/system/ham-cw.service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl restart "$SERVICE"

echo ""
echo "=== ham-cw installed ==="
echo "Web UI: http://$(hostname -I | awk '{print $1}')"
echo "Update: curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/update.sh | bash"
