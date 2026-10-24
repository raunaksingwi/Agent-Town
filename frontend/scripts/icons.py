"""Agent Town's app icon: a pixel house on the night-blue sky, as PNGs and an SVG. Pure standard library.

    python3 scripts/icons.py public
"""
import struct, sys, zlib
from pathlib import Path

# 16x16 pixel art. . sky, R roof, r roof shade, W wall, D door, L lit window, G grass
ART = """
................
................
.......RR.......
......RRRR......
.....RRrrRR.....
....RRrrrrRR....
...RRrrrrrrRR...
..RRRRRRRRRRRR..
...WWWWWWWWWW...
...WLLWWWWLLW...
...WLLWDDWLLW...
...WWWWDDWWWW...
...WWWWDDWWWW...
GGGGGGGGGGGGGGGG
GGGGGGGGGGGGGGGG
................
""".split()
COL = {".": (0x1f, 0x3f, 0x68), "R": (0xc8, 0x4b, 0x31), "r": (0xa3, 0x37, 0x22), "W": (0xf6, 0xeb, 0xcf),
       "D": (0x7a, 0x4e, 0x2c), "L": (0xf2, 0xc1, 0x4e), "G": (0x5d, 0x9e, 0x4a)}

def png(size: int, pad: float) -> bytes:
    inner = int(size * (1 - 2 * pad)); cell = inner / 16; off = (size - inner) / 2
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            gx, gy = int((x - off) // cell), int((y - off) // cell)
            ch = ART[gy][gx] if 0 <= gx < 16 and 0 <= gy < 16 else "."
            row += bytes(COL[ch])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")

def svg() -> str:
    rects = "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="#{COL[c][0]:02x}{COL[c][1]:02x}{COL[c][2]:02x}"/>'
                    for y, line in enumerate(ART) for x, c in enumerate(line) if c != ".")
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges"><rect width="16" height="16" fill="#1f3f68"/>{rects}</svg>\n'

out = Path(sys.argv[1])
out.joinpath("icon-192.png").write_bytes(png(192, 0.06))
out.joinpath("icon-512.png").write_bytes(png(512, 0.06))
out.joinpath("icon-maskable-512.png").write_bytes(png(512, 0.16))   # Android crops maskable icons to a circle
out.joinpath("apple-touch-icon.png").write_bytes(png(180, 0.06))
out.joinpath("icon.svg").write_text(svg())
