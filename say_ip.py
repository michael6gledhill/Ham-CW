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
    """Use espeak piped to the ReSpeaker 2-Mic HAT via ALSA."""
    # Ensure WM8960 output mixers are unmuted and volume is up
    for ctrl in ["Speaker", "Playback", "Left Output Mixer PCM",
                 "Right Output Mixer PCM"]:
        subprocess.run(["amixer", "-c", "seeed2micvoicec", "sset", ctrl, "on"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["amixer", "-c", "seeed2micvoicec", "sset", "Speaker", "100%"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["amixer", "-c", "seeed2micvoicec", "sset", "Playback", "100%"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # espeak -> wav -> aplay on the ReSpeaker HAT
    espeak = subprocess.Popen(
        ["espeak", "-s", "130", "--stdout", text],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    subprocess.run(
        ["aplay", "-D", "plughw:seeed2micvoicec,0"],
        stdin=espeak.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    espeak.wait()


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
