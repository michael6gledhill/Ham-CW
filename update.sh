#!/usr/bin/env bash
# ham-cw update script
# Run remotely with:
#   curl -fsSL http://<pi-ip>:8080/update | bash
# Or pull direct from your repo host:
#   curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/update.sh | bash
#
# What it does:
#   1. Pulls the latest code from git
#   2. Installs Python dependencies
#   3. Installs ALSA config + systemd service
#   4. Restarts the ham-cw systemd service

set -euo pipefail

REPO_URL="https://github.com/michael6gledhill/Ham-CW.git"
INSTALL_DIR="${HAM_CW_DIR:-$HOME/Ham-CW}"
SERVICE="ham-cw"

# Clone if not present, otherwise pull
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "[ham-cw update] pulling latest code..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "[ham-cw update] cloning repo to $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# Stop the old Rust binary if it's running
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    echo "[ham-cw update] stopping old service..."
    sudo systemctl stop "$SERVICE"
fi

echo "[ham-cw update] installing Python dependencies..."
sudo apt-get install -y --no-install-recommends python3-alsaaudio espeak 2>/dev/null || true

# Install ALSA dmix config for ReSpeaker HAT (allows audio sharing)
if [ -f "$INSTALL_DIR/asoundrc" ]; then
    echo "[ham-cw update] installing ~/.asoundrc (ALSA dmix for ReSpeaker)..."
    cp "$INSTALL_DIR/asoundrc" "$HOME/.asoundrc"
fi

# Install / update systemd service
if [ -f "$INSTALL_DIR/ham-cw.service" ]; then
    echo "[ham-cw update] installing systemd service..."
    sudo cp "$INSTALL_DIR/ham-cw.service" /etc/systemd/system/ham-cw.service
    sudo systemctl daemon-reload
    sudo systemctl enable ham-cw
fi

if systemctl is-active --quiet "$SERVICE"; then
    echo "[ham-cw update] restarting $SERVICE..."
    sudo systemctl restart "$SERVICE"
    echo "[ham-cw update] done — service restarted."
else
    echo "[ham-cw update] done — binary updated. (Service not running; start with: sudo systemctl start $SERVICE)"
fi
