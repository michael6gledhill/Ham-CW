#!/usr/bin/env bash
# ham-cw update script
# Usage:  bash update.sh
#   or:   curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/update.sh | bash

set -euo pipefail

REPO_URL="https://github.com/michael6gledhill/Ham-CW.git"
INSTALL_DIR="${HAM_CW_DIR:-$HOME/Ham-CW}"
SERVICE="ham-cw"

# 1. Clone or pull latest code
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "[ham-cw] pulling latest code..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "[ham-cw] cloning repo to $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 2. Install dependencies (only if missing)
for pkg in python3-pigpio pigpio python3-alsaaudio python3-tk; do
    dpkg -s "$pkg" &>/dev/null || {
        echo "[ham-cw] installing $pkg..."
        sudo apt-get install -y --no-install-recommends "$pkg"
    }
done

# Ensure pigpio daemon is running
sudo systemctl enable pigpiod 2>/dev/null
sudo systemctl start pigpiod 2>/dev/null

# 3. Update systemd service, daemon-reload, enable, restart
echo "[ham-cw] updating systemd service..."
sudo cp "$INSTALL_DIR/ham-cw.service" /etc/systemd/system/ham-cw.service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl restart "$SERVICE"
echo "[ham-cw] done -- service restarted."
