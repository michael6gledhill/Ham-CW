#!/usr/bin/env bash
# ham-cw install script for Raspberry Pi Zero (Raspberry Pi OS / Raspbian)
# Run once as the pi user: bash install.sh

set -e

echo "=== ham-cw installer ==="

# 1. System packages ----------------------------------------------------------
echo "Updating package list..."
sudo apt-get update -qq

echo "Installing build dependencies..."
sudo apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libasound2-dev \
    curl

# 2. Rust toolchain -----------------------------------------------------------
if ! command -v cargo > /dev/null 2>&1; then
    echo "Installing Rust toolchain..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
    # shellcheck source=/dev/null
    source "$HOME/.cargo/env"
else
    echo "Rust already installed: $(rustc --version)"
fi

# 3. GPIO group ---------------------------------------------------------------
if ! groups "$USER" | grep -q gpio; then
    echo "Adding $USER to gpio group..."
    sudo usermod -a -G gpio "$USER"
    echo "NOTE: Log out and back in (or reboot) for group change to take effect."
fi

# 4. Build --------------------------------------------------------------------
echo "Building ham-cw (this takes a few minutes on Pi Zero)..."
cd "$(dirname "$0")"

# Source cargo env in case we just installed Rust
export PATH="$HOME/.cargo/bin:$PATH"

cargo build --release

BINARY="./target/release/ham-cw"
echo ""
echo "Build complete."
echo "Binary: $BINARY  ($(du -sh "$BINARY" | cut -f1))"
echo ""
echo "=== Quick start ==="
echo "  $BINARY           # 20 WPM (default)"
echo "  $BINARY 25        # 25 WPM"
echo "  $BINARY --help    # show pin reference"
echo ""
echo "Wiring:"
echo "  GPIO 12 (pin 32)  DIT paddle"
echo "  GPIO 13 (pin 33)  DAH paddle"
echo "  GPIO 16 (pin 36)  TX switch (high = transmit enabled)"
echo "  GPIO 20 (pin 38)  SPK switch (not currently used)"
echo "  GPIO 18 (pin 12)  PTT output to radio"
echo ""
echo "To autostart on boot, run:"
echo "  sudo cp ham-cw.service /etc/systemd/system/"
echo "  sudo systemctl enable --now ham-cw"
