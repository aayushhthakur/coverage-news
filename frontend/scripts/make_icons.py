"""Draw the app icon (ranked bars on a blue tile) as PNGs, using only the standard library.

    python3 scripts/make_icons.py
"""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
BG, FG = (29, 91, 216), (255, 255, 255)


def png(size: int, maskable: bool) -> bytes:
    r = 0 if maskable else size * 0.22            # maskable icons are full-bleed squares
    pad = size * (0.28 if maskable else 0.22)       # keep bars inside the maskable safe zone
    bars = [(0.30, 1.00), (0.48, 0.72), (0.66, 0.46)]   # (y centre, length fraction)
    h = size * 0.10
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            # rounded-square mask
            cx = min(max(x, r), size - 1 - r)
            cy = min(max(y, r), size - 1 - r)
            inside = (x - cx) ** 2 + (y - cy) ** 2 <= r * r if r else True
            if not inside:
                row += bytes((0, 0, 0, 0))
                continue
            col = BG
            for yc, frac in bars:
                y0, x0 = size * yc - h / 2, pad
                x1 = pad + (size - 2 * pad) * frac
                if y0 <= y <= y0 + h and x0 <= x <= x1:
                    col = FG
            row += bytes((*col, 255))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


OUT.mkdir(parents=True, exist_ok=True)
for size in (192, 512):
    (OUT / f"icon-{size}.png").write_bytes(png(size, False))
    (OUT / f"maskable-{size}.png").write_bytes(png(size, True))
(OUT / "icon.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" fill="#1d5bd8"/>'
    '<g fill="#fff"><rect x="22" y="25" width="56" height="10"/><rect x="22" y="43" width="40" height="10"/>'
    '<rect x="22" y="61" width="26" height="10"/></g></svg>')
print("icons written to", OUT)
