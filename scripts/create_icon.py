#!/usr/bin/env python3
"""Create the app icon using only the Python standard library."""

import binascii
import struct
import zlib
from pathlib import Path


SIZE = 1024


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)


def main():
    rows = []
    bars = [(300, 390), (420, 300), (540, 210), (660, 340)]
    for y in range(SIZE):
        row = bytearray([0])
        for x in range(SIZE):
            radius = 190
            inside = radius <= x < SIZE - radius or radius <= y < SIZE - radius
            if not inside:
                cx = radius if x < radius else SIZE - radius - 1
                cy = radius if y < radius else SIZE - radius - 1
                inside = (x - cx) ** 2 + (y - cy) ** 2 <= radius**2
            color = (10, 18, 34, 255) if inside else (0, 0, 0, 0)
            for center, height in bars:
                if abs(x - center) < 34 and abs(y - SIZE // 2) < height // 2:
                    color = (90, 220, 205, 255)
                    break
            row.extend(color)
        rows.append(row)
    raw = b"".join(rows)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    output = Path(__file__).resolve().parents[1] / "build" / "icon.png"
    output.write_bytes(png)
    print(output)


if __name__ == "__main__":
    main()
