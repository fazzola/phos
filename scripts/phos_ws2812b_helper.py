#!/usr/bin/env python3
"""Root-owned WS2812B helper; accepts bounded pixel frames over a Unix socket."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sys


def args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--pin", type=int, required=True)
    parser.add_argument("--socket", default="/run/phos-led.sock")
    parser.add_argument("--group", default="gpio")
    return parser.parse_args()


def main():
    settings = args()
    if os.geteuid() != 0:
        raise SystemExit("PHOS WS2812B helper must run as root")
    if settings.count <= 0 or not 0 <= settings.pin <= 27:
        raise SystemExit("--count must be positive and --pin must be BCM GPIO 0 through 27")
    from grp import getgrnam
    from rpi_ws281x import Color, PixelStrip, ws
    path = Path(settings.socket)
    path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(str(path))
    server.settimeout(.5)
    os.chown(path, 0, getgrnam(settings.group).gr_gid)
    os.chmod(path, 0o660)
    # The helper receives logical RGB from PHOS. WS2812B uses GRB bytes on
    # the wire, which rpi-ws281x handles through this explicit strip type.
    strip = PixelStrip(settings.count, settings.pin, brightness=255,
                       strip_type=ws.WS2811_STRIP_GRB)
    strip.begin()
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    try:
        while running:
            try:
                payload, _ = server.recvfrom(65536)
                pixels = json.loads(payload).get("pixels")
                if not isinstance(pixels, list) or len(pixels) != settings.count:
                    continue
                for index, color in enumerate(pixels):
                    if not isinstance(color, list) or len(color) != 3 or any(type(channel) is not int or not 0 <= channel <= 255 for channel in color):
                        break
                    strip.setPixelColor(index, Color(*color))
                else:
                    strip.show()
            except (socket.timeout, OSError, ValueError, json.JSONDecodeError):
                continue
    finally:
        for index in range(settings.count): strip.setPixelColor(index, 0)
        strip.show(); server.close(); path.unlink(missing_ok=True)


if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: sys.exit(0)
