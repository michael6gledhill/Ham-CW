#!/usr/bin/env bash
# ham-cw install script for Raspberry Pi 4
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
    python3-alsaaudio \
    python3-tk \
    git

# 2. Enable pigpio daemon (DMA-timed PWM)
echo "[ham-cw] enabling pigpio daemon..."
sudo systemctl enable pigpiod
sudo systemctl start pigpiod

# 3. GPIO group
if ! groups "$USER" | grep -q gpio; then
    echo "[ham-cw] adding $USER to gpio group..."
    sudo usermod -a -G gpio "$USER"
fi

# 4. Clone or pull repo
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "[ham-cw] pulling latest code..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "[ham-cw] cloning repo to $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 5. Systemd service
echo "[ham-cw] installing systemd service..."
sudo cp "$INSTALL_DIR/ham-cw.service" /etc/systemd/system/ham-cw.service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl restart "$SERVICE"

echo ""
echo "=== ham-cw installed ==="
echo "The keyer GUI should appear on the touchscreen."
echo "Update: curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/update.sh | bash"
