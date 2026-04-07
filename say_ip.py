#!/usr/bin/env python3
"""Speak the Pi's IP address through the audio output."""

import socket
import subprocess
import tempfile
import os


def get_ip():
    """Get the primary LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def speak(text):
    """Use espeak to say text through ALSA audio."""
    subprocess.run(["espeak", "-s", "130", text],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ip = get_ip()
    if ip:
        # Spell out each digit so espeak reads clearly
        # e.g. "192.168.1.42" -> "1 9 2  dot  1 6 8  dot  1  dot  4 2"
        parts = ip.split(".")
        readable = " dot ".join(" ".join(d for d in octet) for octet in parts)
        speak(f"My IP address is {readable}")
    else:
        speak("No network connection")


if __name__ == "__main__":
    main()
