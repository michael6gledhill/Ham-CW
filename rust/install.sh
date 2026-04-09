#!/usr/bin/env bash
# Install the Rust ham-cw binary on a Raspberry Pi
# Run this ON the Pi after copying the binary over.

set -euo pipefail

INSTALL_DIR="${HAM_CW_DIR:-$HOME/Ham-CW/rust}"
SERVICE="ham-cw"

echo "=== ham-cw (Rust) installer ==="

# 1. Minimal system deps — just ALSA dev libs for audio
echo "[ham-cw] installing ALSA libraries..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends libasound2-dev

# 2. Make binary executable
chmod +x "${INSTALL_DIR}/ham-cw"

# 3. Systemd service
echo "[ham-cw] installing systemd service..."
sudo cp "${INSTALL_DIR}/ham-cw.service" /etc/systemd/system/ham-cw.service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl restart "$SERVICE"

echo ""
echo "[ham-cw] installed and running!"
echo "  Web UI: http://$(hostname -I | awk '{print $1}')"
echo "  Logs:   sudo journalctl -u ham-cw -f"
