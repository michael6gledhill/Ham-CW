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
        # Replace dots with " dot " so espeak reads each octet clearly
        readable = ip.replace(".", " dot ")
        speak(f"My IP address is {readable}")
    else:
        speak("No network connection")


if __name__ == "__main__":
    main()
