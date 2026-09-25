#!/usr/bin/env python3
"""Standalone WS2812B ring smoke test; does not import or start PHOS."""
from __future__ import annotations

import argparse
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, required=True, help="Exact number of LEDs in the ring")
    parser.add_argument("--pin", type=int, default=18, help="BCM GPIO data pin (default: 18)")
    parser.add_argument("--brightness", type=int, default=32, choices=range(1, 256), metavar="1..255",
                        help="Driver brightness, 1 through 255 (default: 32)")
    parser.add_argument("--seconds", type=float, default=.8, help="Seconds for each color (default: 0.8)")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.count <= 0 or args.pin < 0 or args.pin > 27 or args.seconds <= 0:
        raise SystemExit("--count and --seconds must be positive; --pin must be BCM GPIO 0 through 27")
    try:
        from rpi_ws281x import Color, PixelStrip
    except ImportError:
        raise SystemExit("rpi-ws281x is not installed. Install it with: pip install 'rpi-ws281x>=5.0,<6'")

    strip = PixelStrip(args.count, args.pin, brightness=args.brightness)
    started = False
    try:
        strip.begin()
        started = True
        for label, color in (("red", Color(255, 0, 0)), ("green", Color(0, 255, 0)),
                             ("blue", Color(0, 0, 255)), ("white", Color(255, 255, 255))):
            print(f"Showing {label} on {args.count} LEDs via BCM GPIO {args.pin}", flush=True)
            for index in range(args.count):
                strip.setPixelColor(index, color)
            strip.show()
            time.sleep(args.seconds)
    finally:
        # Always leave the ring dark, including after Ctrl+C or an initialization error.
        if started:
            for index in range(args.count):
                strip.setPixelColor(index, Color(0, 0, 0))
            strip.show()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped; LEDs were turned off.", file=sys.stderr)
