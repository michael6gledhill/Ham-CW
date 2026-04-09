#!/usr/bin/env bash
# Cross-compile ham-cw (Rust) for Raspberry Pi Zero W (armv6/arm-unknown-linux-gnueabihf)
# Run on your dev machine (x86_64 Linux/macOS/WSL)
#
# Prerequisites:
#   rustup target add arm-unknown-linux-gnueabihf
#   sudo apt install gcc-arm-linux-gnueabihf   # or cross / cargo-cross

set -euo pipefail

cd "$(dirname "$0")"

TARGET="arm-unknown-linux-gnueabihf"

echo "[ham-cw] building for ${TARGET} (Pi Zero W)..."

# Use cross if available, otherwise raw cargo
if command -v cross &>/dev/null; then
    cross build --release --target "${TARGET}"
else
    cargo build --release --target "${TARGET}"
fi

BIN="target/${TARGET}/release/ham-cw"
echo "[ham-cw] built: ${BIN}"
ls -lh "${BIN}"
echo "[ham-cw] done — deploy with: scp ${BIN} pi@pizero-ham:~/Ham-CW/ham-cw"
