"""Title-screen logo helpers: read the BG3 logo (stripe rows + 2bpp GFX 28..2B) into an RGB canvas."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import lz2_ref as L  # noqa: E402

GFX_FIRST = 0x28
STRIPE_ROW0 = 0x2B5C9      # file offset of row-9 stripe ($05:B5C9)
STRIPE_STRIDE = 0x34
ROW0, ROWS = 9, 5
COL0, COLS = 3, 25
# CGRAM palettes 2/6/7 of the title screen (colour 1 = black, 2 and 3 = fills), from a frame dump
PALS = {
    2: [None, (0, 0, 0), (0, 200, 0), (0, 216, 248)],
    6: [None, (0, 0, 0), (0, 216, 248), (248, 200, 40)],
    7: [None, (0, 0, 0), (248, 56, 56), (0, 200, 0)],
}
BLACK = (0, 0, 0)


def load_tiles(rom):
    tiles = bytearray()
    for j in range(4):
        d, _ = L.decompress(rom, L.gfx_source_addr(rom, GFX_FIRST + j))
        assert len(d) == 2048, len(d)
        tiles += d
    return tiles  # 512 tiles x 16 bytes (2bpp)


def tile_pixels(tiles, t):
    o = t * 16
    return [[((tiles[o + 2 * y] >> (7 - x)) & 1) | (((tiles[o + 2 * y + 1] >> (7 - x)) & 1) << 1)
             for x in range(8)] for y in range(8)]


def encode_tile(px):
    out = bytearray(16)
    for y in range(8):
        b0 = b1 = 0
        for x in range(8):
            c = px[y][x]
            b0 |= (c & 1) << (7 - x)
            b1 |= ((c >> 1) & 1) << (7 - x)
        out[2 * y], out[2 * y + 1] = b0, b1
    return bytes(out)


def stripe_rows(rom):
    """Parse the five logo-row stripes -> list of (file_offset_of_data, words list)."""
    o, rows = STRIPE_ROW0, []
    for _ in range(ROWS):
        n = ((rom[o + 2] << 8) | rom[o + 3]) + 1
        rows.append((o + 4, [struct.unpack_from("<H", rom, o + 4 + 2 * i)[0] for i in range(n // 2)]))
        o += 4 + n
    return rows


def read_rows(rom):
    out = []
    for _, w in stripe_rows(rom):
        out.append(w + [0x0FC | (6 << 10)] * (COLS - len(w)))   # blank = tile FC pal 6
    return out


def canvas_from(rom):
    """Return (RGBA-ish list of rows: colour tuple or None) of size (ROWS*8) x (COLS*8)."""
    tiles = load_tiles(rom)
    rows = read_rows(rom)
    h, w = ROWS * 8, COLS * 8
    cv = [[None] * w for _ in range(h)]
    for r, row in enumerate(rows):
        for c, e in enumerate(row):
            t, p = e & 0x3FF, (e >> 10) & 7
            fx, fy = e & 0x4000, e & 0x8000
            px = tile_pixels(tiles, t)
            for y in range(8):
                for x in range(8):
                    v = px[7 - y if fy else y][7 - x if fx else x]
                    if v and p in PALS:
                        cv[r * 8 + y][c * 8 + x] = PALS[p][v]
    return cv, tiles, rows


STRIPE_START, STRIPE_END = 0x2B4D9, 0x2B6FD      # whole title stripe chain ($05:B4D9..), ends with $FF


def other_tile_ids(rom):
    """Tile ids referenced by every stripe record of the title chain except the five logo-row records."""
    ids, o, k = set(), STRIPE_START, 0
    while o < STRIPE_END and rom[o] != 0xFF:
        n = (((rom[o + 2] << 8) | rom[o + 3]) & 0x3FFF) + 1
        if o != STRIPE_ROW0 and not (STRIPE_ROW0 < o < STRIPE_ROW0 + 5 * 0x36):
            if rom[o + 3] != 0 or True:
                for i in range(n // 2):
                    ids.add(struct.unpack_from("<H", rom, o + 4 + 2 * i)[0] & 0x3FF)
        o += 4 + n
    return ids
