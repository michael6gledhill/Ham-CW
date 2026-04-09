#!/usr/bin/env bash
# ham-cw Rust installer for Raspberry Pi
# Usage: curl -sSL https://raw.githubusercontent.com/cadet/Ham-CW/main/rust/install-rust.sh | bash
#   or:  bash install-rust.sh

set -euo pipefail

REPO="https://github.com/cadet/Ham-CW.git"
INSTALL_DIR="$HOME/Ham-CW"
SERVICE_NAME="ham-cw"
BIN_DIR="$INSTALL_DIR/rust"

echo "============================================"
echo "  ham-cw (Rust) installer for Raspberry Pi"
echo "============================================"
echo ""

# -----------------------------------------------------------
#  1. System dependencies
# -----------------------------------------------------------
echo "[1/6] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    build-essential \
    libasound2-dev \
    pkg-config \
    git \
    curl

# -----------------------------------------------------------
#  2. Install Rust (if not present)
# -----------------------------------------------------------
echo ""
echo "[2/6] Checking Rust toolchain..."
if command -v rustc &>/dev/null; then
    echo "  Rust already installed: $(rustc --version)"
    rustup update stable --no-self-update 2>/dev/null || true
else
    echo "  Installing Rust via rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
    source "$HOME/.cargo/env"
    echo "  Installed: $(rustc --version)"
fi

# Make sure cargo is on PATH for this session
export PATH="$HOME/.cargo/bin:$PATH"

# -----------------------------------------------------------
#  3. Clone or update repo
# -----------------------------------------------------------
echo ""
echo "[3/6] Getting source code..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Updating existing repo..."
    cd "$INSTALL_DIR"
    git pull --ff-only
else
    echo "  Cloning repo..."
    git clone "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# -----------------------------------------------------------
#  4. Build release binary
# -----------------------------------------------------------
echo ""
echo "[4/6] Building ham-cw (this takes a while on Pi Zero)..."
cd "$BIN_DIR"
cargo build --release 2>&1

BIN="target/release/ham-cw"
if [ ! -f "$BIN" ]; then
    echo "ERROR: build failed — binary not found"
    exit 1
fi

cp "$BIN" "$BIN_DIR/ham-cw"
chmod +x "$BIN_DIR/ham-cw"
echo "  Built: $(ls -lh "$BIN_DIR/ham-cw" | awk '{print $5}')"

# -----------------------------------------------------------
#  5. Stop old Python service if running
# -----------------------------------------------------------
echo ""
echo "[5/6] Checking for old Python service..."
if systemctl is-active --quiet ham-cw-python 2>/dev/null || \
   systemctl is-active --quiet ham_cw 2>/dev/null; then
    echo "  Stopping old Python service..."
    sudo systemctl stop ham-cw-python 2>/dev/null || true
    sudo systemctl stop ham_cw 2>/dev/null || true
    sudo systemctl disable ham-cw-python 2>/dev/null || true
    sudo systemctl disable ham_cw 2>/dev/null || true
fi

# -----------------------------------------------------------
#  6. Install and start systemd service
# -----------------------------------------------------------
echo ""
echo "[6/6] Setting up systemd service..."

cat <<EOF | sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null
[Unit]
Description=ham-cw CW keyer (Rust)
After=network.target

[Service]
Type=simple
WorkingDirectory=${BIN_DIR}
ExecStart=${BIN_DIR}/ham-cw
Restart=on-failure
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    IP=$(hostname -I | awk '{print $1}')
    echo ""
    echo "============================================"
    echo "  ham-cw installed and running!"
    echo ""
    echo "  Web UI:  http://${IP}"
    echo "  Logs:    sudo journalctl -u ham-cw -f"
    echo "  Status:  sudo systemctl status ham-cw"
    echo "  Restart: sudo systemctl restart ham-cw"
    echo "============================================"
else
    echo ""
    echo "WARNING: service failed to start. Check logs:"
    echo "  sudo journalctl -u ham-cw --no-pager -n 20"
    exit 1
fi
