#!/usr/bin/env python3
"""Redraw the SMW title logo "MARIO" as "PEACH" (-> SUPER PEACH WORLD).

The logo is BG3 (2bpp): rows 9..13 of the map come from five stripe records at $05:B5C9 and the tiles
from compressed GFX files $28..$2B (tile id = 128*(file-0x28) + index).  We rebuild the logo as an RGB
canvas, wipe the MARIO part, draw PEACH, then re-tile (each 8x8 cell may use one palette: 2, 6 or 7).
"""
import argparse
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import lz2_encode  # noqa: E402
import lz2_ref  # noqa: E402
import title_logo as T  # noqa: E402

FONT = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
GREEN, CYAN, YELLOW, RED = (0, 200, 0), (0, 216, 248), (248, 200, 40), (248, 56, 56)
# letter, fill colour, x0, width  (canvas x; the fill is 22 px tall, y 8..29).  The art is deliberately blocky
# and cell-aligned: the title shares its 512 BG3 tiles with other screens, so only the 32 MARIO-only tiles are free.  Neighbouring letters
# must be colour pairs one palette can hold: green/cyan (pal 2), cyan/yellow (pal 6), red/green (pal 7).
LETTERS = [("P", CYAN, 8, 16), ("E", GREEN, 26, 14), ("A", RED, 42, 14), ("C", GREEN, 58, 15), ("H", CYAN, 76, 14)]
# tile ids never referenced by any BG3 map while sampling the title, file-select and erase screens
EXTRA_FREE = []
STEM, BAR = 6, 6
WIPE_X = 95          # canvas x >= this is the untouched "WORLD" part
FILL_Y0, FILL_H = 8, 22


def _rect(m, x0, y0, x1, y1):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            m[y][x] = True


def glyph_mask(ch, w, h):
    """Blocky letter built from stems and bars (repeats across 8x8 cells, so it needs few unique tiles)."""
    m = [[False] * w for _ in range(h)]
    T_, B_ = STEM, BAR                 # stem / bar thickness
    top, bot = 0, h - 1
    mid = (h - B_) // 2
    if ch == "P":
        _rect(m, 0, top, T_ - 1, bot)
        _rect(m, 0, top, w - 1, top + B_ - 1)
        _rect(m, 0, mid - 1, w - 1, mid + B_ - 2)
        _rect(m, w - T_, top, w - 1, mid + B_ - 2)
    elif ch == "E":
        _rect(m, 0, top, T_ - 1, bot)
        _rect(m, 0, top, w - 1, top + B_ - 1)
        _rect(m, 0, mid, w - 3, mid + B_ - 1)
        _rect(m, 0, bot - B_ + 1, w - 1, bot)
    elif ch == "A":
        _rect(m, 0, top, T_ - 1, bot)
        _rect(m, w - T_, top, w - 1, bot)
        _rect(m, 0, top, w - 1, top + B_ - 1)
        _rect(m, 0, mid, w - 1, mid + B_ - 1)
    elif ch == "C":
        _rect(m, 0, top, T_ - 1, bot)
        _rect(m, 0, top, w - 1, top + B_ - 1)
        _rect(m, 0, bot - B_ + 1, w - 1, bot)
        _rect(m, w - 5, top, w - 1, top + 9)
        _rect(m, w - 5, bot - 9, w - 1, bot)
    elif ch == "H":
        _rect(m, 0, top, T_ - 1, bot)
        _rect(m, w - T_, top, w - 1, bot)
        _rect(m, 0, mid, w - 1, mid + B_ - 1)
    # round the outer corners by one pixel
    for cx, cy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        m[cy][cx] = False
    return m


def draw_peach(cv):
    H, W = len(cv), len(cv[0])
    for y in range(H):
        for x in range(WIPE_X):
            cv[y][x] = None
    fill = {}
    for ch, col, x0, w in LETTERS:
        m = glyph_mask(ch, w, FILL_H)
        for y in range(FILL_H):
            for x in range(w):
                if m[y][x]:
                    fill[(x0 + x, FILL_Y0 + y)] = col
    ink = set(fill)
    outline = {(x + dx, y + dy) for (x, y) in ink for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    shadow = {(x + k, y + k) for (x, y) in outline for k in (1, 2)}
    for (x, y) in outline | shadow:
        if 0 <= x < WIPE_X and 0 <= y < H:
            cv[y][x] = T.BLACK
    for (x, y), c in fill.items():
        cv[y][x] = c


def _flips(px):
    for fx in (0, 1):
        for fy in (0, 1):
            yield (fx << 14) | (fy << 15), [[px[7 - y if fy else y][7 - x if fx else x] for x in range(8)] for y in range(8)]


def quantize(cv, base_rows, tiles, other_ids=frozenset()):
    """-> (new_rows words, new_tiles bytearray, report). Tiles are reused (also flipped) or taken from MARIO-only ids."""
    tiles = bytearray(tiles)
    known = {}                                   # encoded tile -> (tile id, flip bits to reach it)
    for i in range(512):
        for fl, f in _flips(T.tile_pixels(tiles, i)):
            known.setdefault(T.encode_tile(f), (i, fl))
    changed_cols = range(0, WIPE_X // 8 + 1)
    used_outside = {e & 0x3FF for row in base_rows for c, e in enumerate(row) if c not in changed_cols} | set(other_ids)
    used_inside = {e & 0x3FF for row in base_rows for c, e in enumerate(row) if c in changed_cols}
    free = sorted(used_inside - used_outside - {0xFC}) + EXTRA_FREE
    # tiles about to be reused must not be matched against their stale contents
    for t in free:
        for k in [k for k, v in known.items() if v[0] == t]:
            del known[k]
    out = [list(row) for row in base_rows]
    next_free = 0
    conflicts = []
    for r in range(T.ROWS):
        for c in range(T.COLS):
            if c not in changed_cols:
                continue
            cells = [[cv[r * 8 + y][c * 8 + x] for x in range(8)] for y in range(8)]
            fills = {p for row in cells for p in row if p not in (None, T.BLACK)}
            if not any(p for row in cells for p in row):
                out[r][c] = 0x0FC | (6 << 10)
                continue
            pal = next((k for k, cols in T.PALS.items() if fills <= {cols[2], cols[3]}), None)
            if pal is None:
                conflicts.append((r, c, sorted(fills)))
                pal = 6
            idx = {v: i for i, v in enumerate(T.PALS[pal]) if v}
            px = [[0 if p is None else (1 if p == T.BLACK else idx.get(p, 1)) for p in row] for row in cells]
            data = T.encode_tile(px)
            if data in known:
                tid, fl = known[data]
            else:
                if next_free >= len(free):
                    raise SystemExit("out of free logo tiles")
                tid, fl = free[next_free], 0
                next_free += 1
                tiles[tid * 16:tid * 16 + 16] = data
                for f2, f in _flips(px):
                    known.setdefault(T.encode_tile(f), (tid, f2))
            # `known` stores the flip that turns the stored tile into the *looked-up* image
            out[r][c] = tid | fl | (pal << 10)
    return out, tiles, dict(conflicts=conflicts, tiles_used=next_free, tiles_free=len(free))


def apply(rom, preview=None):
    cv, tiles, base_rows = T.canvas_from(rom)
    orig_w = [list(r) for r in cv]
    draw_peach(cv)
    new_rows, new_tiles, rep = quantize(cv, base_rows, tiles, T.other_tile_ids(bytes(rom)))
    if rep["conflicts"]:
        raise SystemExit(f"palette conflicts: {rep['conflicts']}")
    # write stripe words (only the columns that are present in each record)
    for (off, words), nr in zip(T.stripe_rows(rom), new_rows):
        for i in range(len(words)):
            struct.pack_into("<H", rom, off + 2 * i, nr[i])
    # recompress the four GFX files into their original slots
    addrs = [lz2_ref.gfx_source_addr(bytes(rom), T.GFX_FIRST + j) for j in range(4)]
    for j in range(4):
        enc = lz2_encode.encode(bytes(new_tiles[j * 2048:(j + 1) * 2048]))
        a = addrs[j]
        off = lz2_ref.lorom(bytes(rom), a)
        old, _ = lz2_ref.decompress(bytes(rom), a)
        # slot = distance to the next GFX file start (files are packed back to back)
        nxt = [x for x in (lz2_ref.gfx_source_addr(bytes(rom), k) for k in range(0x32)) if x > a]
        slot = lz2_ref.lorom(bytes(rom), min(nxt)) - off
        print(f"GFX {T.GFX_FIRST + j:02X}: {len(enc)} bytes (slot {slot})")
        if len(enc) > slot:
            raise SystemExit("recompressed title GFX does not fit its slot")
        rom[off:off + slot] = enc.ljust(slot, b"\xff")[:slot] if False else enc + bytes(rom[off + len(enc):off + slot])
        got, _ = lz2_ref.decompress(bytes(rom), a)
        assert bytes(got) == bytes(new_tiles[j * 2048:(j + 1) * 2048]), "GFX roundtrip"
    if preview:
        cv2, _, _ = T.canvas_from(bytes(rom))
        im = Image.new("RGB", (len(cv2[0]), len(cv2)), (40, 40, 40))
        for y, r in enumerate(cv2):
            for x, c in enumerate(r):
                if c:
                    im.putpixel((x, y), c)
        im.resize((im.width * 6, im.height * 6), Image.NEAREST).save(preview)
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--preview")
    a = ap.parse_args()
    rom = bytearray(Path(a.rom).read_bytes())
    print(apply(rom, a.preview))
    Path(a.out).write_bytes(rom)


if __name__ == "__main__":
    main()
