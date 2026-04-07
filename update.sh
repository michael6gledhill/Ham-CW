#!/usr/bin/env bash
# ham-cw update script
# Run remotely with:
#   curl -fsSL http://<pi-ip>:8080/update | bash
# Or pull direct from your repo host:
#   curl -fsSL https://raw.githubusercontent.com/michael6gledhill/Ham-CW/main/update.sh | bash
#
# What it does:
#   1. Pulls the latest code from git
#   2. Rebuilds the release binary
#   3. Installs it to /usr/local/bin
#   4. Restarts the ham-cw systemd service

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE="ham-cw"

echo "[ham-cw update] pulling latest code..."
git -C "$REPO_DIR" pull --ff-only

echo "[ham-cw update] building release binary..."
cargo build --release --manifest-path "$REPO_DIR/Cargo.toml"

echo "[ham-cw update] installing binary..."
sudo install -m 755 "$REPO_DIR/target/release/ham-cw" /usr/local/bin/ham-cw

if systemctl is-active --quiet "$SERVICE"; then
    echo "[ham-cw update] restarting $SERVICE..."
    sudo systemctl restart "$SERVICE"
    echo "[ham-cw update] done — service restarted."
else
    echo "[ham-cw update] done — binary updated. (Service not running; start with: sudo systemctl start $SERVICE)"
fi
