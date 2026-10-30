#!/usr/bin/env python3
"""Build a Peach-skinned copy of the SMW (USA) ROM from an owner ROM + sprite sheet.

Replaces core player poses in the compressed GFX32 sheet (Mario graphics) and
Mario's 10-colour palette.  Code is untouched, so the recompiled game runs it
as-is; mod packages (which pin the stock ROM hash) will not apply to the output.

Sprites: Princess Peach, SMW-style, by WizToad and GatetcVerde (Mario Worlds
Delta) -- please give credit if used.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import lz2_encode  # noqa: E402
import lz2_ref  # noqa: E402
import slice_sheet  # noqa: E402
import smw_player as P  # noqa: E402

GFX32_ROM = 0x40000          # $08:8000
GFX32_SLOT = 16320           # bytes available before the next file
PAL_ADDR = 0xB2C8            # Mario's 10-colour palette (small/big/cape)

# (pose, frame name) per power-up.  Poses are SMW PlayerPose ($13E0) values.
BIG = [
    (0x00, "big1_00"), (0x01, "big1_01"), (0x02, "big1_02"),   # stand / walk
    (0x03, "big1_04"),                                          # look up
    (0x04, "big1_08"), (0x05, "big1_09"), (0x06, "big1_10"),   # fast walk / run
    (0x3C, "big1_05"),                                          # duck
    (0x0B, "big1_12"),                                          # jump
    (0x0D, "big1_06"),                                          # skid
    (0x24, "big3_05"),                                          # fall
    (0x25, "big3_02"),                                          # back view (climb)
    (0x0F, "big3_01"),                                          # face screen
    (0x07, "big2_00"), (0x08, "big2_01"), (0x09, "big2_02"),   # carrying
]
SMALL = [
    (0x00, "small1_01"), (0x01, "small1_02"), (0x02, "small1_03"),
    (0x03, "small1_04"),
    (0x04, "small1_01"), (0x05, "small1_02"), (0x06, "small1_03"),
    (0x3C, "small1_05"),
    (0x0B, "small1_10"),
    (0x0D, "small1_06"),
    (0x24, "small1_11"),
    (0x25, "small2_08"),
    (0x0F, "small2_07"),
    (0x07, "small1_06"), (0x08, "small1_07"), (0x09, "small1_08"),
]


# Best-guess pairings for the remaining poses (chosen by eye from the contact sheets;
# verify in game).  Applied after BIG / SMALL, so shared tiles keep the verified frame.
BIG_GUESS = [
    (0x0A, "big3_00"), (0x0C, "big1_11"), (0x0E, "big1_03"),
    (0x14, "big4_01"), (0x26, "big4_01"), (0x15, "big4_02"),
    (0x16, "big3_07"), (0x17, "big3_07"), (0x18, "big1_09"), (0x19, "big1_10"),
    (0x1A, "big3_06"), (0x1B, "big3_06"), (0x1C, "big2_05"), (0x1D, "big2_04"),
    (0x1E, "big4_03"), (0x1F, "big4_04"),
    (0x20, "big3_08"), (0x21, "big3_09"), (0x22, "big4_00"), (0x23, "big4_00"),
    (0x27, "big3_08"), (0x28, "big3_07"), (0x29, "big3_10"),
    (0x32, "big1_07"), (0x33, "big4_02"), (0x34, "big4_02"), (0x35, "big3_08"),
    (0x36, "big3_00"), (0x37, "big2_08"), (0x38, "big4_04"), (0x39, "big4_02"),
    (0x3A, "big2_09"), (0x3B, "big2_10"), (0x3D, "big4_00"), (0x3E, "big4_01"),
    (0x3F, "big3_07"), (0x42, "big2_04"), (0x44, "big4_02"), (0x45, "big1_03"),
]
SMALL_GUESS = [
    (0x0A, "small2_06"), (0x0C, "small1_11"), (0x0E, "small1_03"),
    (0x14, "small2_09"), (0x26, "small2_09"), (0x15, "small2_08"),
    (0x16, "small2_13"), (0x17, "small2_13"), (0x18, "small1_07"), (0x19, "small1_08"),
    (0x1A, "small2_12"), (0x1B, "small2_12"), (0x1C, "small1_12"), (0x1D, "small1_15"),
    (0x1E, "small2_08"), (0x1F, "small2_08"),
    (0x20, "small2_11"), (0x21, "small2_11"), (0x22, "small2_07"), (0x23, "small2_07"),
    (0x27, "small2_11"), (0x28, "small2_13"), (0x29, "small2_14"),
    (0x32, "small1_09"), (0x33, "small2_08"), (0x34, "small2_08"), (0x35, "small2_10"),
    (0x36, "small2_06"), (0x37, "small2_01"), (0x38, "small2_08"), (0x39, "small2_08"),
    (0x3A, "small2_02"), (0x3B, "small2_03"), (0x3D, "small2_07"), (0x3E, "small2_09"),
    (0x3F, "small2_13"), (0x42, "small1_15"), (0x44, "small2_08"), (0x45, "small2_07"),
]
# No Peach frame fits these (diagonal slope poses, star/hurt flash, wide end pose, cape spins
# for small): they keep Mario's art.  See MISSING.md.
BIG_MISSING = [0x10, 0x11, 0x12, 0x13, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x43]
SMALL_MISSING = [0x10, 0x11, 0x12, 0x13, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x43]


def squeeze(frame, max_w, max_h):
    """Shrink a frame by deleting the most redundant rows/columns (pixel-art friendly).

    The top quarter of rows (crown/face) and outer columns are never removed."""
    px = [[frame.getpixel((x, y)) for x in range(frame.width)] for y in range(frame.height)]

    def diff(a, b):
        return sum(1 for p, q in zip(a, b) if p != q)

    while len(px) > max_h:
        lo = max(1, len(px) // 4)
        best = min(range(lo, len(px)), key=lambda i: diff(px[i], px[i - 1]) - (0.5 if i == len(px) - 1 else 0))
        del px[best]
    while px and len(px[0]) > max_w:
        cols = list(zip(*px))
        w = len(cols)
        best = min(range(1, w - 1), key=lambda i: diff(cols[i], cols[i - 1]))
        for row in px:
            del row[best]
    out = Image.new("RGBA", (len(px[0]), len(px)), (0, 0, 0, 0))
    for y, row in enumerate(px):
        for x, v in enumerate(row):
            out.putpixel((x, y), v)
    return out


def frame_images(sheet_path):
    im, bg, frames = slice_sheet.slice_sheet(sheet_path)
    out = {}
    for f in frames:
        c = im.crop(f["box"]).convert("RGBA")
        px = c.load()
        for y in range(c.height):
            for x in range(c.width):
                if px[x, y][:3] == bg:
                    px[x, y] = (0, 0, 0, 0)
        key = f["name"].replace("_", "", 0)
        band, idx = f["name"].rsplit("_", 1)
        out[f"{band}_{int(idx):02d}"] = c
    return out


def make_palette(images, count=10):
    """Median-cut a shared palette; slot 0 of the returned list is the darkest."""
    tiles = [im for im in images]
    w = sum(i.width for i in tiles)
    h = max(i.height for i in tiles)
    comp = Image.new("RGB", (w, h), (255, 0, 255))
    x = 0
    for i in tiles:
        rgb = Image.new("RGB", i.size, (255, 0, 255))
        rgb.paste(i.convert("RGB"), mask=i.split()[3])
        comp.paste(rgb, (x, 0))
        x += i.width
    q = comp.quantize(colors=count + 1, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = q.getpalette()[:3 * (count + 1)]
    cols = [tuple(pal[i:i + 3]) for i in range(0, len(pal), 3)]
    # drop the colour closest to the magenta key
    key = min(cols, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, (255, 0, 255))))
    cols.remove(key)
    return cols[:count]


def nearest(cols, rgb):
    return min(range(len(cols)), key=lambda i: sum((a - b) ** 2 for a, b in zip(cols[i], rgb)))


def to_bgr555(c):
    r, g, b = (v >> 3 for v in c)
    return r | (g << 5) | (b << 10)


def place(canvas_w, canvas_h, frame, cx, bottom):
    """Return a W x H list of (r,g,b)|None with the frame centred on cx, feet on `bottom`."""
    bbox = frame.getbbox()
    fx0, fy0, fx1, fy1 = bbox
    shift_x = cx - (fx0 + fx1) // 2
    shift_y = bottom - fy1
    out = [[None] * canvas_w for _ in range(canvas_h)]
    px = frame.load()
    for y in range(frame.height):
        for x in range(frame.width):
            r, g, b, a = px[x, y]
            if a:
                X, Y = x + shift_x, y + shift_y
                if 0 <= X < canvas_w and 0 <= Y < canvas_h:
                    out[Y][X] = (r, g, b)
    return out


def tile_bytes(canvas, pal, t, tx, ty, n, W, H, OX, OY):
    """4bpp SNES bytes of sheet sub-tile (tx, ty) of OAM tile t.

    The sheet art faces left and the game X-flips it for right-facing Mario, so the
    stored pixels are the mirror image of what appears on screen."""
    px = [[0] * 8 for _ in range(8)]
    for yy in range(8):
        for xx in range(8):
            X = OX + t["x"] + (n - 1 - tx) * 8 + (7 - xx)
            Y = OY + t["y"] + ty * 8 + yy
            c = canvas[Y][X] if 0 <= X < W and 0 <= Y < H else None
            px[yy][xx] = 0 if c is None else 6 + nearest(pal, c)
    new = bytearray(32)
    for yy in range(8):
        b0 = b1 = b2 = b3 = 0
        for xx in range(8):
            v, bit = px[yy][xx], 7 - xx
            b0 |= (v & 1) << bit
            b1 |= ((v >> 1) & 1) << bit
            b2 |= ((v >> 2) & 1) << bit
            b3 |= ((v >> 3) & 1) << bit
        new[yy * 2], new[yy * 2 + 1] = b0, b1
        new[16 + yy * 2], new[17 + yy * 2] = b2, b3
    return bytes(new)


PEACH_TILES = [0x19, 0x0E, 0x0A, 0x0C, 0x11]   # P E A C H in the SMW text font
MARIO_TILES = [0x16, 0x0A, 0x1B, 0x12, 0x18]


def patch_text(rom):
    """MARIO -> PEACH in the on-screen text (same 5 letters, so tilemaps keep their size)."""
    n = 0
    for stride in (2,):
        i = 0
        while True:
            hits = [k for k in range(len(rom) - 10) if all(rom[k + j * stride] == MARIO_TILES[j] for j in range(5))]
            break
        for k in hits:
            for j, t in enumerate(PEACH_TILES):
                rom[k + j * stride] = t
            n += 1
    # status bar and COURSE CLEAR header draw MARIO with dedicated tiles 30..34
    for k in range(len(rom) - 10):
        if all(rom[k + j * 2] == 0x30 + j for j in range(5)) and rom[k + 1] == 0x28 and rom[k + 9] == 0x28:
            for j, t in enumerate(PEACH_TILES):
                rom[k + j * 2] = t
            n += 1
    print("text patched:", n, "places")


def fix_checksum(rom):
    """LoROM header checksum/complement at $7FDC-$7FDF."""
    rom[0x7FDC:0x7FE0] = b"\xff\xff\x00\x00"
    c = sum(rom) & 0xFFFF
    struct.pack_into("<HH", rom, 0x7FDC, c ^ 0xFFFF, c)


def make_ips(old, new):
    out = bytearray(b"PATCH")
    i, n = 0, len(old)
    while i < n:
        if old[i] == new[i]:
            i += 1
            continue
        j = i
        while j < n and j - i < 0xFFFF and (old[j] != new[j] or (j + 1 < n and old[j + 1] != new[j + 1])):
            j += 1
        j = max(j, i + 1)
        out += bytes([i >> 16 & 255, i >> 8 & 255, i & 255, (j - i) >> 8 & 255, (j - i) & 255]) + new[i:j]
        i = j
    return bytes(out + b"EOF")


def build(rom_path, sheet_path, out_path, report_path=None, ips_path=None):
    rom = bytearray(Path(rom_path).read_bytes())
    if len(rom) != 0x80000:
        raise SystemExit("expected a 512 KiB headerless SMW (USA) ROM")
    pl = P.Player(bytes(rom))
    stock_pl = pl  # decoded before any repaint
    sheet = bytearray(pl.sheet)
    imgs = frame_images(sheet_path)
    chosen = [imgs[name] for _, name in BIG + SMALL + BIG_GUESS + SMALL_GUESS]
    pal = make_palette(chosen)
    print("palette", pal)

    written = {}
    conflicts = 0
    W, H, OX, OY = 64, 64, 24, 8
    for powerup, selection in ((1, BIG + BIG_GUESS), (0, SMALL + SMALL_GUESS)):
        for pose, name in selection:
            tiles, pieces, _ = pl.pose_tiles(pose, powerup, 1)
            large = [t for t in tiles if t["large"]]
            if not large:
                continue
            # Align to where stock Mario's feet are actually drawn (small Mario
            # straddles both 16x16 tiles; big fills them).
            stock = P.render_pose(stock_pl, pose, powerup, 1).split()[3].getbbox()
            if not stock:
                continue
            top = OY + large[0]["y"]
            bottom = stock[3] - 1
            cx = OX + large[0]["x"] + 8
            frame = squeeze(imgs[name], 16, bottom - top + 1)
            canvas = place(W, H, frame, cx, bottom)
            for t in tiles:
                n = 2 if t["large"] else 1
                for ty in range(n):
                    for tx in range(n):
                        src = pl.vram_tile_source(t["tile"] + tx + 16 * ty, pieces)
                        new = tile_bytes(canvas, pal, t, tx, ty, n, W, H, OX, OY)
                        if src in written and written[src][1] != new:
                            conflicts += 1
                            continue
                        written[src] = (pose, new)
                        sheet[src * 32:src * 32 + 32] = new
    print("tiles repainted:", len(written), "conflicts:", conflicts)

    # Encode exactly the original decompressed length: the game decompresses to $7E:2000 and
    # Yoshi's expanded graphics start right after it at $7E:7D00, so extra bytes would erase him.
    enc = lz2_encode.encode(bytes(sheet[:pl.sheet_len]))
    assert len(lz2_ref.decompress(bytes(0x40000) + enc.ljust(0x8000, b"\xff"), 0x088000)[0]) == pl.sheet_len
    print("compressed", len(enc), "bytes; slot", GFX32_SLOT)
    if len(enc) > GFX32_SLOT:
        raise SystemExit("recompressed GFX32 does not fit its ROM slot")
    rom[GFX32_ROM:GFX32_ROM + GFX32_SLOT] = enc.ljust(GFX32_SLOT, b"\xff")

    # palette: index 6..15 -> 10 BGR555 words (index 0 of the table = colour 6)
    pa = PAL_ADDR - 0x8000
    for i, c in enumerate(pal):
        struct.pack_into("<H", rom, pa + 2 * i, to_bgr555(c))
    # Fire Peach: same colours, dress turned white/grey (Fire Mario's palette is the next 20 bytes at $00:B2F0)
    fire = list(pal)
    fire[6], fire[7] = (248, 248, 248), (200, 200, 184)
    fa = 0xB2F0 - 0x8000
    for i, c in enumerate(fire):
        struct.pack_into("<H", rom, fa + 2 * i, to_bgr555(c))
    patch_text(rom)
    import build_title
    build_title.apply(rom)
    fix_checksum(rom)
    Path(out_path).write_bytes(rom)
    if ips_path:
        Path(ips_path).write_bytes(make_ips(Path(rom_path).read_bytes(), bytes(rom)))
    if report_path:
        json.dump({"palette": pal, "tiles": len(written), "conflicts": conflicts,
                   "compressed": len(enc)}, open(report_path, "w"), indent=1)
    return bytes(rom)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report")
    ap.add_argument("--ips", help="also write an IPS patch (stock -> Peach)")
    a = ap.parse_args()
    build(a.rom, a.sheet, a.out, a.report, a.ips)
