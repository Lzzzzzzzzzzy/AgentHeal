"""Dependency-free PNG drawing: a 5x7 bitmap font, rectangles, lines and simple shapes.

Used for render-only figures (values that exist only as pixels). Pure Python keeps the gym runnable without Pillow.
"""
from __future__ import annotations

import random
import struct
import zlib

FONT = {  # 5x7 glyphs, rows top->bottom, bit 4 = leftmost pixel
    "0": [14, 17, 19, 21, 25, 17, 14], "1": [4, 12, 4, 4, 4, 4, 14], "2": [14, 17, 1, 2, 4, 8, 31],
    "3": [31, 2, 4, 2, 1, 17, 14], "4": [2, 6, 10, 18, 31, 2, 2], "5": [31, 16, 30, 1, 1, 17, 14],
    "6": [6, 8, 16, 30, 17, 17, 14], "7": [31, 1, 2, 4, 8, 8, 8], "8": [14, 17, 17, 14, 17, 17, 14],
    "9": [14, 17, 17, 15, 1, 2, 12], ".": [0, 0, 0, 0, 0, 12, 12], ",": [0, 0, 0, 0, 12, 4, 8],
    "-": [0, 0, 0, 31, 0, 0, 0], " ": [0] * 7, ":": [0, 12, 12, 0, 12, 12, 0], "/": [1, 1, 2, 4, 8, 16, 16],
    "%": [24, 25, 2, 4, 8, 19, 3], "(": [2, 4, 8, 8, 8, 4, 2], ")": [8, 4, 2, 2, 2, 4, 8],
    "A": [14, 17, 17, 31, 17, 17, 17], "B": [30, 17, 17, 30, 17, 17, 30], "C": [14, 17, 16, 16, 16, 17, 14],
    "D": [30, 17, 17, 17, 17, 17, 30], "E": [31, 16, 16, 30, 16, 16, 31], "F": [31, 16, 16, 30, 16, 16, 16],
    "G": [14, 17, 16, 23, 17, 17, 15], "H": [17, 17, 17, 31, 17, 17, 17], "J": [7, 2, 2, 2, 2, 18, 12],
    "K": [17, 18, 20, 24, 20, 18, 17], "L": [16, 16, 16, 16, 16, 16, 31], "M": [17, 27, 21, 21, 17, 17, 17],
    "N": [17, 17, 25, 21, 19, 17, 17], "P": [30, 17, 17, 30, 16, 16, 16], "Q": [14, 17, 17, 17, 21, 18, 13],
    "R": [30, 17, 17, 30, 20, 18, 17], "S": [15, 16, 16, 14, 1, 1, 30], "T": [31, 4, 4, 4, 4, 4, 4],
    "U": [17, 17, 17, 17, 17, 17, 14], "V": [17, 17, 17, 17, 17, 10, 4], "W": [17, 17, 17, 21, 21, 21, 10],
    "X": [17, 17, 10, 4, 10, 17, 17], "Y": [17, 17, 10, 4, 4, 4, 4], "Z": [31, 1, 2, 4, 8, 16, 31],
    "a": [0, 0, 14, 1, 15, 17, 15], "b": [16, 16, 22, 25, 17, 17, 30], "c": [0, 0, 14, 16, 16, 17, 14],
    "d": [1, 1, 13, 19, 17, 17, 15], "e": [0, 0, 14, 17, 31, 16, 14], "g": [0, 15, 17, 17, 15, 1, 14],
    "h": [16, 16, 22, 25, 17, 17, 17], "k": [16, 16, 18, 20, 24, 20, 18], "l": [12, 4, 4, 4, 4, 4, 14],
    "m": [0, 0, 26, 21, 21, 17, 17], "n": [0, 0, 22, 25, 17, 17, 17], "o": [0, 0, 14, 17, 17, 17, 14],
    "p": [0, 0, 30, 17, 30, 16, 16], "r": [0, 0, 22, 25, 16, 16, 16], "s": [0, 0, 14, 16, 14, 1, 30],
    "t": [8, 8, 28, 8, 8, 9, 6], "u": [0, 0, 17, 17, 17, 19, 13], "y": [0, 0, 17, 17, 15, 1, 14],
    "²": [12, 2, 4, 8, 14, 0, 0], "L": [16, 16, 16, 16, 16, 16, 31],
}


class Canvas:
    def __init__(self, w: int, h: int, bg=(255, 255, 255)):
        self.w, self.h = w, h
        self.px = [list(bg) * w for _ in range(h)]

    def set(self, x: int, y: int, c) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            row = self.px[y]
            row[3 * x:3 * x + 3] = c

    def rect(self, x0, y0, x1, y1, c) -> None:
        for y in range(max(0, y0), min(self.h, y1)):
            for x in range(max(0, x0), min(self.w, x1)):
                self.set(x, y, c)

    def line(self, x0, y0, x1, y1, c) -> None:
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(n + 1):
            self.set(round(x0 + (x1 - x0) * i / n), round(y0 + (y1 - y0) * i / n), c)

    def text(self, x, y, s, c=(0, 0, 0), scale=3, jitter: random.Random | None = None) -> None:
        cx = x
        for ch in s:
            g = FONT.get(ch) or FONT.get(ch.upper()) or FONT[" "]
            dy = jitter.randint(-scale, scale) if jitter else 0
            for r, bits in enumerate(g):
                for col in range(5):
                    if bits & (1 << (4 - col)):
                        self.rect(cx + col * scale, y + dy + r * scale, cx + (col + 1) * scale,
                                  y + dy + (r + 1) * scale, c)
            cx += 6 * scale + (jitter.randint(0, scale) if jitter else 0)

    def circle(self, cx, cy, r, c) -> None:
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    self.set(x, y, c)

    def triangle(self, cx, cy, r, c) -> None:
        for y in range(cy - r, cy + r + 1):
            half = int((y - (cy - r)) / 2)
            for x in range(cx - half, cx + half + 1):
                self.set(x, y, c)

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(row) for row in self.px)

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def figure_png(title: str, entity: str, value: str, unit: str, others: list[tuple[str, str]]) -> bytes:
    """A bar-chart-like figure whose labels carry the values (render-only data)."""
    rows = [(entity, value)] + others[:4]
    c = Canvas(560, 60 + 34 * len(rows))
    c.text(10, 10, title[:40], (20, 20, 60), scale=2)
    for i, (k, v) in enumerate(rows):
        y = 50 + 34 * i
        c.text(10, y, str(k)[:12], (0, 0, 0), scale=2)
        try:
            frac = min(1.0, float(str(v).replace(",", "")) / (1.6 * float(str(value).replace(",", "")) + 1e-9))
        except ValueError:
            frac = 0.5
        c.rect(170, y, 170 + int(220 * frac), y + 16, (70, 120, 200))
        c.text(400, y, f"{v} {unit}"[:14], (0, 0, 0), scale=2)
    return c.png()
